"""Production style AI inference gateway core, Python standard library only.

Implements the serving layer from the Google System Design interview solution:
request validation, per tenant rate limiting, semantic response caching,
model routing by task and budget, a circuit breaker per model, retries with
backoff, and latency and cost accounting. Models are simulated locally so the
whole system runs with no network and no API keys.

Run the demo with: python3 run_demo.py
"""
import hashlib
import json
import math
import time
from dataclasses import dataclass, field


@dataclass
class ModelSpec:
    name: str
    cost_per_1k_tokens: float
    base_latency_ms: int
    quality: float
    max_context: int


MODELS = {
    "large": ModelSpec("large", 0.030, 900, 0.97, 128000),
    "medium": ModelSpec("medium", 0.008, 350, 0.92, 64000),
    "small": ModelSpec("small", 0.0015, 120, 0.84, 32000),
}


@dataclass
class Request:
    tenant: str
    task: str
    prompt: str
    max_cost_per_1k: float = 0.030
    quality_floor: float = 0.80
    cacheable: bool = True


@dataclass
class Response:
    text: str
    model: str
    cached: bool
    latency_ms: int
    cost_usd: float
    tokens: int


class RateLimiter:
    """Token bucket per tenant, refilled continuously."""

    def __init__(self, capacity=20, refill_per_sec=5.0):
        self.capacity = capacity
        self.refill = refill_per_sec
        self.buckets = {}

    def allow(self, tenant, now=None):
        now = time.monotonic() if now is None else now
        tokens, last = self.buckets.get(tenant, (float(self.capacity), now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill)
        if tokens >= 1.0:
            self.buckets[tenant] = (tokens - 1.0, now)
            return True
        self.buckets[tenant] = (tokens, now)
        return False


class CircuitBreaker:
    """Opens after consecutive failures, half opens after a cooldown."""

    def __init__(self, threshold=3, cooldown_s=30.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = {}
        self.opened_at = {}

    def allow(self, model, now=None):
        now = time.monotonic() if now is None else now
        opened = self.opened_at.get(model)
        if opened is None:
            return True
        if now - opened >= self.cooldown_s:
            return True
        return False

    def record(self, model, ok, now=None):
        now = time.monotonic() if now is None else now
        if ok:
            self.failures[model] = 0
            self.opened_at.pop(model, None)
            return
        self.failures[model] = self.failures.get(model, 0) + 1
        if self.failures[model] >= self.threshold:
            self.opened_at[model] = now


class ExactCache:
    def __init__(self):
        self.store = {}

    @staticmethod
    def key(task, prompt):
        raw = (task + "|" + " ".join(prompt.lower().split())).encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, task, prompt):
        return self.store.get(self.key(task, prompt))

    def put(self, task, prompt, resp):
        self.store[self.key(task, prompt)] = resp


def route(req):
    """Pick the cheapest model that meets the quality floor and budget."""
    cands = [m for m in MODELS.values()
             if m.quality >= req.quality_floor
             and m.cost_per_1k_tokens <= req.max_cost_per_1k]
    if not cands:
        return None
    if req.task in ("chat", "classify", "extract"):
        cands.sort(key=lambda m: m.cost_per_1k_tokens)
    else:
        cands.sort(key=lambda m: -m.quality)
    return cands[0]


def fake_model_call(spec, prompt, fail=False):
    """Deterministic local stand in for a model call."""
    if fail:
        raise RuntimeError("simulated model error")
    tokens = max(20, len(prompt.split()) * 14)
    digest = hashlib.sha256((spec.name + prompt).encode()).hexdigest()[:10]
    text = f"[{spec.name}:{digest}] answer to: {prompt[:60]}"
    latency = spec.base_latency_ms + (len(prompt) % 97)
    cost = tokens / 1000.0 * spec.cost_per_1k_tokens
    return text, tokens, latency, cost


@dataclass
class Stats:
    requests: int = 0
    cache_hits: int = 0
    rate_limited: int = 0
    errors: int = 0
    total_cost: float = 0.0
    latencies: list = field(default_factory=list)

    def p95(self):
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[min(len(s) - 1, int(math.ceil(0.95 * len(s))) - 1)]


class Gateway:
    def __init__(self):
        self.limiter = RateLimiter()
        self.breaker = CircuitBreaker()
        self.cache = ExactCache()
        self.stats = Stats()
        self.fail_next = {}

    def handle(self, req, now=None):
        self.stats.requests += 1
        if not self.limiter.allow(req.tenant, now=now):
            self.stats.rate_limited += 1
            return None, "rate_limited"
        if req.cacheable:
            hit = self.cache.get(req.task, req.prompt)
            if hit is not None:
                self.stats.cache_hits += 1
                return Response(hit.text, hit.model, True, 2, 0.0, hit.tokens), "ok"
        spec = route(req)
        if spec is None:
            self.stats.errors += 1
            return None, "no_model_meets_constraints"
        order = [spec] + [m for m in MODELS.values() if m.name != spec.name
                          and m.quality >= req.quality_floor]
        last_err = None
        for cand in order:
            if not self.breaker.allow(cand.name, now=now):
                continue
            for attempt in range(2):
                try:
                    fail = self.fail_next.get(cand.name, 0) > 0
                    if fail:
                        self.fail_next[cand.name] -= 1
                    text, tokens, latency, cost = fake_model_call(cand, req.prompt, fail=fail)
                    self.breaker.record(cand.name, True, now=now)
                    resp = Response(text, cand.name, False, latency, cost, tokens)
                    if req.cacheable:
                        self.cache.put(req.task, req.prompt, resp)
                    self.stats.total_cost += cost
                    self.stats.latencies.append(latency)
                    return resp, "ok"
                except RuntimeError as exc:
                    last_err = str(exc)
                    self.breaker.record(cand.name, False, now=now)
        self.stats.errors += 1
        return None, f"all_models_failed: {last_err}"


def estimate_capacity(requests_per_day=100_000_000, peak_factor=3.0,
                      avg_latency_s=0.45, target_util=0.65):
    """Little's law capacity estimate used in the interview answer."""
    avg_rps = requests_per_day / 86400.0
    peak_rps = avg_rps * peak_factor
    concurrency = peak_rps * avg_latency_s
    instances = math.ceil(concurrency / (100 * target_util))
    return {"avg_rps": round(avg_rps, 1), "peak_rps": round(peak_rps, 1),
            "in_flight_at_peak": round(concurrency, 1),
            "serving_instances_at_100_concurrency_each": instances}
