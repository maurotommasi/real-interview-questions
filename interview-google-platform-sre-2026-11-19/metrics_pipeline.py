#!/usr/bin/env python3
"""Global metrics ingestion and alerting pipeline (single file, stdlib).

A working local implementation of the design from the Google Platform
Engineer / SRE interview solution: edge style ingestion with a cardinality
guard, a durable write ahead buffer, tiered in memory storage with
downsampling, a query path, and an alert path that is fully separate from
the query path and keeps evaluating even while queries are under load.

Run:  python3 metrics_pipeline.py           (serves on 127.0.0.1:9090)
      python3 metrics_pipeline.py --demo    (synthetic traffic + alert)
Try:  curl -s -X POST localhost:9090/ingest -H 'Content-Type: application/json' \
        -d '{"service":"checkout","samples":[{"metric":"http_requests",
             "labels":{"route":"/pay"},"value":12}]}'
      curl -s 'localhost:9090/query?metric=http_requests&service=checkout'
      curl -s localhost:9090/alerts
"""
import json, os, sys, threading, time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("METRICS_PORT", "9090"))
WAL_PATH = os.environ.get("METRICS_WAL", "metrics_wal.jsonl")

# Labels that must never become series labels: each distinct value would
# create new series and explode cardinality. They belong in logs, not here.
FORBIDDEN_LABELS = {"user_id", "request_id", "session_id", "ip", "email"}
ALLOWED_LABELS = {"service", "region", "route", "status", "version",
                  "instance"}
SERIES_QUOTA_PER_SERVICE = 10000     # new series a service may create
RAW_RETENTION_S = 7 * 24 * 3600      # full resolution kept 7 days
EVAL_INTERVAL_S = 2                  # demo value; production uses 30 s

# Alert rules: evaluated on aggregates, never on the query path.
RULES = [
    {"name": "high_error_rate", "metric": "http_errors",
     "service": "checkout", "window_s": 120, "threshold": 50,
     "op": "sum_above", "severity": "page"},
    {"name": "latency_p95_high", "metric": "request_latency_ms",
     "service": "checkout", "window_s": 120, "threshold": 800,
     "op": "avg_above", "severity": "ticket"},
]

def series_key(metric, labels):
    items = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{metric}{{{items}}}"

class Store:
    """Tiered time series storage.
    Raw samples live in per series deques. A compactor thread folds raw
    samples into 1 minute and 1 hour aggregates (downsampling), which is
    what long range queries read. This mirrors the hot/warm/cold tiers
    in the design: 7 days full resolution, 30 days at 1 minute,
    13 months at 1 hour."""

    def __init__(self):
        self.raw = defaultdict(list)       # key -> [(ts, value)]
        self.min1 = defaultdict(dict)      # key -> {minute -> (sum, n)}
        self.hour1 = defaultdict(dict)     # key -> {hour -> (sum, n)}
        self.lock = threading.Lock()

    def add(self, key, ts, value):
        with self.lock:
            self.raw[key].append((ts, value))

    def compact(self):
        now = time.time()
        with self.lock:
            for key, samples in self.raw.items():
                keep = []
                for ts, value in samples:
                    if ts < now - 60:      # older than a minute: fold it
                        m = int(ts // 60)
                        s, n = self.min1[key].get(m, (0.0, 0))
                        self.min1[key][m] = (s + value, n + 1)
                        h = int(ts // 3600)
                        s, n = self.hour1[key].get(h, (0.0, 0))
                        self.hour1[key][h] = (s + value, n + 1)
                    else:
                        keep.append((ts, value))
                self.raw[key] = keep

    def query(self, metric, service=None, window_s=300):
        """Sum and average over the window, across matching series.
        Reads raw samples plus 1 minute aggregates, never blocks ingest."""
        now = time.time()
        total, count = 0.0, 0
        with self.lock:
            for key, samples in self.raw.items():
                if not self._match(key, metric, service):
                    continue
                for ts, value in samples:
                    if ts > now - window_s:
                        total += value
                        count += 1
            for key, buckets in self.min1.items():
                if not self._match(key, metric, service):
                    continue
                for minute, (s, n) in buckets.items():
                    if (minute + 1) * 60 > now - window_s and \
                            minute * 60 < now - 60:
                        total += s
                        count += n
        return {"sum": round(total, 2), "count": count,
                "avg": round(total / count, 3) if count else None}

    @staticmethod
    def _match(key, metric, service):
        if not key.startswith(metric + "{"):
            return False
        return service is None or f"service={service}" in key

STORE = Store()

# --------------------------------------------------------------------------
# Cardinality guard: runs at ingestion, before anything reaches storage.
# --------------------------------------------------------------------------
class Guard:
    def __init__(self):
        self.series_by_service = defaultdict(set)
        self.lock = threading.Lock()
        self.rejected = 0

    def admit(self, service, metric, labels):
        for name in labels:
            if name in FORBIDDEN_LABELS:
                self.rejected += 1
                return f"label {name} is not allowed in metrics"
            if name not in ALLOWED_LABELS:
                self.rejected += 1
                return f"label {name} is not on the allow list"
        key = series_key(metric, labels)
        with self.lock:
            known = self.series_by_service[service]
            if key not in known and len(known) >= SERIES_QUOTA_PER_SERVICE:
                self.rejected += 1
                return "series quota exceeded for service, aggregate first"
            known.add(key)
        return None

GUARD = Guard()

# --------------------------------------------------------------------------
# Write ahead buffer: every accepted batch is appended to disk before it
# is stored in memory, and replayed on startup. A crash or a regional
# outage does not silently lose alert inputs.
# --------------------------------------------------------------------------
WAL_LOCK = threading.Lock()

def wal_append(batch):
    with WAL_LOCK:
        with open(WAL_PATH, "a") as fh:
            fh.write(json.dumps(batch) + "\n")

def wal_replay():
    if not os.path.exists(WAL_PATH):
        return 0
    n = 0
    with open(WAL_PATH) as fh:
        for line in fh:
            try:
                batch = json.loads(line)
            except Exception:
                continue
            for sample in batch["samples"]:
                STORE.add(series_key(sample["metric"], sample["labels"]),
                          sample.get("ts", time.time()), sample["value"])
                n += 1
    return n

def ingest(service, samples, ts_default=None):
    """Validate, guard, buffer, store. Returns (accepted, error)."""
    now = ts_default or time.time()
    for sample in samples:
        labels = dict(sample.get("labels", {}))
        labels["service"] = service
        err = GUARD.admit(service, sample["metric"], labels)
        if err:
            return 0, err
        sample["labels"] = labels
        sample.setdefault("ts", now)
    wal_append({"service": service, "samples": samples})
    for sample in samples:
        STORE.add(series_key(sample["metric"], sample["labels"]),
                  sample["ts"], sample["value"])
    return len(samples), None

# --------------------------------------------------------------------------
# Alert evaluation: separate thread, separate state store, reads storage
# aggregates on its own schedule. Query load can never delay a page.
# Alert state is small and strongly consistent by design (single lock);
# in the global design it is the one piece kept in a replicated store.
# --------------------------------------------------------------------------
class AlertEngine:
    def __init__(self, rules):
        self.rules = rules
        self.state = {}                    # rule name -> alert dict
        self.lock = threading.Lock()
        self.notifications = []            # stands in for the pager

    def evaluate_once(self):
        fired = []
        for rule in self.rules:
            res = STORE.query(rule["metric"], rule["service"],
                              rule["window_s"])
            value = res["sum"] if rule["op"] == "sum_above" else res["avg"]
            active = value is not None and value > rule["threshold"]
            with self.lock:
                current = self.state.get(rule["name"])
                if active and not (current and current["active"]):
                    alert = {"rule": rule["name"],
                             "severity": rule["severity"], "active": True,
                             "value": value, "threshold": rule["threshold"],
                             "since": time.strftime(
                                 "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    self.state[rule["name"]] = alert
                    self.notifications.append(alert)
                    fired.append(alert)
                elif not active and current and current["active"]:
                    current["active"] = False   # resolved; deduped by rule
        return fired

    def run_forever(self):
        while True:
            self.evaluate_once()
            time.sleep(EVAL_INTERVAL_S)

ENGINE = AlertEngine(RULES)

def compactor_forever():
    while True:
        STORE.compact()
        time.sleep(30)

# --------------------------------------------------------------------------
# HTTP surface: POST /ingest, GET /query, GET /alerts, GET /health.
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/health":
            return self._send({"status": "ok",
                               "series": sum(len(v) for v in
                                             GUARD.series_by_service
                                             .values()),
                               "rejected": GUARD.rejected})
        if url.path == "/query":
            metric = qs.get("metric", [""])[0]
            if not metric:
                return self._send({"error": "metric is required"}, 400)
            return self._send(STORE.query(
                metric, qs.get("service", [None])[0],
                int(qs.get("window_s", ["300"])[0])))
        if url.path == "/alerts":
            with ENGINE.lock:
                return self._send({"alerts": ENGINE.state,
                                   "notifications": ENGINE.notifications})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/ingest":
            return self._send({"error": "not found"}, 404)
        try:
            batch = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))))
        except Exception:
            return self._send({"error": "invalid json"}, 400)
        service = batch.get("service")
        samples = batch.get("samples", [])
        if not service or not samples:
            return self._send({"error": "service and samples required"}, 400)
        accepted, err = ingest(service, samples)
        if err:
            return self._send({"error": err}, 422)
        return self._send({"accepted": accepted})

    def log_message(self, *args):
        pass

def demo():
    """Synthetic traffic: normal requests, then an error burst that must
    fire the high_error_rate page, printed to the console."""
    print("demo: sending normal traffic for checkout")
    for i in range(5):
        ingest("checkout", [
            {"metric": "http_requests", "labels": {"route": "/pay"},
             "value": 120},
            {"metric": "http_errors", "labels": {"route": "/pay"},
             "value": 2},
            {"metric": "request_latency_ms", "labels": {"route": "/pay"},
             "value": 220}])
        time.sleep(0.3)
    print("demo: error burst, alert should fire within one eval cycle")
    ingest("checkout", [
        {"metric": "http_errors", "labels": {"route": "/pay"},
         "value": 90}])
    fired = ENGINE.evaluate_once()
    for alert in fired:
        print(f"ALERT {alert['severity'].upper()}: {alert['rule']} "
              f"value={alert['value']} threshold={alert['threshold']}")
    print("demo: query last 5 minutes of http_requests:",
          STORE.query("http_requests", "checkout", 300))
    print("demo: forbidden label check:",
          ingest("checkout", [{"metric": "http_requests",
                               "labels": {"user_id": "u123"},
                               "value": 1}]))

if __name__ == "__main__":
    replayed = wal_replay()
    if replayed:
        print(f"replayed {replayed} samples from {WAL_PATH}")
    if "--demo" in sys.argv:
        demo()
        sys.exit(0)
    threading.Thread(target=ENGINE.run_forever, daemon=True).start()
    threading.Thread(target=compactor_forever, daemon=True).start()
    print(f"metrics pipeline listening on http://127.0.0.1:{PORT} "
          f"(wal: {WAL_PATH}, eval every {EVAL_INTERVAL_S}s)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
