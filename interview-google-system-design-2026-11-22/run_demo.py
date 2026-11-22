"""Demo and self check for the inference gateway. Standard library only.

Run: python3 run_demo.py
"""
import json

from gateway import Gateway, Request, estimate_capacity


def main():
    gw = Gateway()
    now = 1000.0
    prompts = [
        Request("acme", "chat", "Summarise the Q3 earnings call"),
        Request("acme", "chat", "Summarise the Q3 earnings call"),
        Request("acme", "reasoning", "Prove the onboarding flow cannot deadlock"),
        Request("globex", "classify", "Tag this support ticket as billing"),
        Request("globex", "extract", "Extract the total from this invoice"),
    ]
    for req in prompts:
        resp, status = gw.handle(req, now=now)
        if resp:
            print(f"{req.task:10s} model={resp.model:7s} cached={resp.cached} "
                  f"latency={resp.latency_ms}ms cost=${resp.cost_usd:.5f}")
        else:
            print(f"{req.task:10s} status={status}")
        now += 0.3

    gw.fail_next["small"] = 5
    resp, status = gw.handle(Request("acme", "chat", "Draft a release note"), now=now + 2)
    print("failure drill:", status, "served by", resp.model if resp else "none")

    cap = estimate_capacity()
    print("capacity:", json.dumps(cap))
    s = gw.stats
    print(f"stats: requests={s.requests} cache_hits={s.cache_hits} "
          f"errors={s.errors} total_cost=${s.total_cost:.5f} p95={s.p95()}ms")
    assert s.cache_hits >= 1, "expected at least one cache hit"
    assert s.requests == 6
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
