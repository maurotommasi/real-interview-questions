"""Multi region AI inference router, interview solution.

Routes each request to the cheapest healthy region that meets the
latency budget, fails over on errors, and records every decision.
Standard library only.
"""
import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class Region:
    name: str
    latency_ms: int
    cost_per_1k: float
    healthy: bool = True
    errors: int = 0


@dataclass
class Request:
    request_id: str
    prompt: str
    max_latency_ms: int
    budget: float


@dataclass
class RouteEvent:
    ts: float
    request_id: str
    region: str
    kind: str
    detail: str


@dataclass
class Router:
    regions: list
    spent: float = 0.0
    events: list = field(default_factory=list)

    def log(self, req_id, region, kind, detail):
        self.events.append(RouteEvent(time.time(), req_id, region, kind, detail))

    def candidates(self, req):
        ok = [r for r in self.regions if r.healthy and r.latency_ms <= req.max_latency_ms]
        return sorted(ok, key=lambda r: r.cost_per_1k)

    def serve(self, req, fail_regions=()):
        for region in self.candidates(req):
            cost = region.cost_per_1k * max(1, len(req.prompt) // 1000 + 1) / 10
            if self.spent + cost > req.budget:
                self.log(req.request_id, region.name, "budget_block", "budget cap reached")
                return {"status": "budget_blocked", "region": None}
            if region.name in fail_regions:
                region.errors += 1
                if region.errors >= 2:
                    region.healthy = False
                self.log(req.request_id, region.name, "failover", "region error, trying next")
                continue
            self.spent += cost
            digest = hashlib.sha256(req.prompt.encode()).hexdigest()[:12]
            self.log(req.request_id, region.name, "served", "output hash " + digest)
            return {"status": "served", "region": region.name, "cost": round(cost, 4)}
        self.log(req.request_id, "", "no_route", "no healthy region in latency budget")
        return {"status": "no_route", "region": None}

    def report(self):
        return {"spent": round(self.spent, 4), "events": len(self.events),
                "healthy": [r.name for r in self.regions if r.healthy]}
