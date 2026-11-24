"""Demo for the multi region inference router. Run: python3 run_demo.py"""
from router import Region, Request, Router

router = Router(regions=[
    Region("us-west", latency_ms=40, cost_per_1k=0.20),
    Region("us-east", latency_ms=70, cost_per_1k=0.18),
    Region("eu-west", latency_ms=120, cost_per_1k=0.22),
])

r1 = router.serve(Request("r1", "summarise this report", max_latency_ms=100, budget=1.00))
print("r1", r1)
r2 = router.serve(Request("r2", "translate this page", max_latency_ms=100, budget=1.00),
                  fail_regions=("us-east",))
print("r2", r2)
r3 = router.serve(Request("r3", "answer in under 50 ms", max_latency_ms=50, budget=1.00),
                  fail_regions=("us-west", "us-west"))
print("r3", r3)
r4 = router.serve(Request("r4", "tight budget request", max_latency_ms=200, budget=0.01))
print("r4", r4)
print("report", router.report())
for e in router.events:
    print("event", e.request_id, e.region, e.kind, e.detail)
