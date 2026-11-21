"""Event producer: generates clickstream events and either writes
them to a JSONL file or posts them to the ingestion service in
batches, the way a web or mobile backend would.

Examples:
    python producer.py --count 20000 --out events.jsonl
    python producer.py --count 20000 --url http://localhost:8090/events
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone

from events import generate


def post_batch(url: str, batch: list[dict]) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({"events": batch}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--span-minutes", type=int, default=60)
    parser.add_argument("--out", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--batch", type=int, default=1000)
    args = parser.parse_args()

    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    events = generate(args.count, start, args.span_minutes)
    print(f"generated {len(events)} events from {events[0]['ts']} "
          f"to {events[-1]['ts']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event) + "\n")
        print(f"wrote {args.out}")
    if args.url:
        totals = {"accepted": 0, "rejected": 0, "duplicates": 0}
        for i in range(0, len(events), args.batch):
            result = post_batch(args.url, events[i : i + args.batch])
            for key in totals:
                totals[key] += result.get(key, 0)
        print(f"posted to {args.url}: {totals}")
    if not args.out and not args.url:
        print("nothing sent: pass --out FILE and/or --url URL")


if __name__ == "__main__":
    main()
