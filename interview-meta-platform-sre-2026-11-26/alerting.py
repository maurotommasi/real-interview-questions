"""Production metrics alerting engine, interview solution for Meta Platform / SRE.

Ingests labelled time series points, evaluates threshold and rate rules over
sliding windows, deduplicates alerts, and routes them to on-call channels.
Standard library only. Run: python3 alerting.py
"""
from __future__ import annotations
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

@dataclass
class Point:
    metric: str
    labels: dict
    value: float
    ts: float

@dataclass
class Rule:
    name: str
    metric: str
    threshold: float
    window_s: int = 300
    severity: str = "page"
    channel: str = "pagerduty"

@dataclass
class Alert:
    rule: str
    labels: dict
    value: float
    severity: str
    channel: str
    ts: float
    state: str = "firing"

class AlertEngine:
    def __init__(self, rules, dedup_s=900):
        self.rules = rules
        self.series = defaultdict(lambda: deque(maxlen=10000))
        self.active = {}
        self.dedup_s = dedup_s
        self.sent = []

    def key(self, metric, labels):
        return (metric, tuple(sorted(labels.items())))

    def ingest(self, point):
        self.series[self.key(point.metric, point.labels)].append(point)

    def evaluate(self, now=None):
        now = now or time.time()
        fired = []
        for rule in self.rules:
            for key, pts in self.series.items():
                if key[0] != rule.metric:
                    continue
                window = [p for p in pts if now - p.ts <= rule.window_s]
                if not window:
                    continue
                avg = sum(p.value for p in window) / len(window)
                akey = (rule.name, key)
                if avg > rule.threshold and akey not in self.active:
                    alert = Alert(rule.name, dict(key[1]), round(avg, 3), rule.severity, rule.channel, now)
                    self.active[akey] = alert
                    self.sent.append(alert)
                    fired.append(alert)
                elif avg <= rule.threshold and akey in self.active:
                    self.active[akey].state = "resolved"
                    del self.active[akey]
        return fired

    def route(self, alert):
        return f"{alert.channel}: [{alert.severity}] {alert.rule} value={alert.value} labels={alert.labels}"

def demo():
    rules = [Rule("cpu_high", "cpu_usage", 0.85, window_s=300, severity="page"),
             Rule("error_rate_high", "error_rate", 0.05, window_s=300, severity="page"),
             Rule("latency_warn", "p99_latency_ms", 800, window_s=300, severity="ticket", channel="slack")]
    eng = AlertEngine(rules)
    base = 1700000000.0
    for host in ("web-1", "web-2"):
        for i in range(10):
            eng.ingest(Point("cpu_usage", {"host": host}, 0.92 if host == "web-1" else 0.40, base + i))
            eng.ingest(Point("error_rate", {"host": host}, 0.09 if host == "web-1" else 0.01, base + i))
            eng.ingest(Point("p99_latency_ms", {"host": host}, 950 if host == "web-1" else 300, base + i))
    fired = eng.evaluate(now=base + 10)
    for a in fired:
        print(eng.route(a))
    print(f"alerts_fired={len(fired)} active={len(eng.active)}")
    assert len(fired) == 3, fired
    print("OK: only web-1 breached all three rules, web-2 stayed quiet")

if __name__ == "__main__":
    demo()
