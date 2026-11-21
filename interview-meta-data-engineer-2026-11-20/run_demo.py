"""End to end demo: producer, ingestion, aggregation, query.

Runs the whole pipeline in one process so you can watch the data
flow, then prints the dashboard numbers the query layer serves.
After the demo you can run the servers for real:

    python ingest.py --port 8090
    python producer.py --count 20000 --url http://localhost:8090/events
    python aggregate.py
    python query.py --port 8091
"""
import os
import shutil
from datetime import datetime, timezone

import aggregate
import ingest
import query
from events import generate


def main() -> None:
    if os.path.exists("data"):
        shutil.rmtree("data")  # start clean so counts are exact
    ingest._seen_ids.clear()

    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    events = generate(20000, start, span_minutes=60)
    # Add one duplicate and one broken event to show dedupe and rejection.
    events.append(dict(events[0]))
    broken = dict(events[1])
    broken["event_id"] = "broken-1"
    del broken["user_id"]
    events.append(broken)

    result = ingest.ingest_events(events)
    print(f"ingestion: {result}")
    assert result["accepted"] == 20000, result
    assert result["rejected"] == 1, result
    assert result["duplicates"] == 1, result

    agg = aggregate.build_rollups()
    print(f"aggregation: {agg}")
    assert agg["events_read"] == 20000, agg

    s = query.summary()
    print(f"summary: {s}")
    assert s["total_events"] == 20000, s
    print("funnel:")
    for step in query.funnel():
        print(f"  {step['step']:<15} {step['events']:>6}  "
              f"{step['pct_of_first']}% of first step")
    series = query.timeseries("purchase")
    print(f"purchase timeseries: {len(series)} minutes, "
          f"{sum(r['events'] for r in series)} purchases")
    print("top pages (most recent hour):", query.top_pages(3))
    print("demo OK: producer, ingestion, aggregation and query all agree")


if __name__ == "__main__":
    main()
