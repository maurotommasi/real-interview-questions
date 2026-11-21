"""Stream aggregation: raw events to dashboard rollups.

Reads the hour partitioned raw JSONL files and builds one minute
rollups in SQLite (data/rollups.db): for every minute, product and
event type, the event count, the number of distinct users, and the
purchase revenue. This is the local equivalent of the streaming job
(Flink or Spark Structured Streaming at Meta scale) that maintains
the same rollups continuously, plus a batch backfill path.

Run after ingestion:  python aggregate.py
Safe to re-run: rollups are rebuilt from raw, so a re-run after a
late data backfill produces corrected numbers.
"""
import glob
import json
import os
import sqlite3
from collections import defaultdict

RAW_PATTERN = os.path.join("data", "raw", "*", "*.jsonl")
DB_PATH = os.path.join("data", "rollups.db")

DDL = """
CREATE TABLE IF NOT EXISTS minute_rollup (
    minute     TEXT NOT NULL,
    product    TEXT NOT NULL,
    event_type TEXT NOT NULL,
    events     INTEGER NOT NULL,
    users      INTEGER NOT NULL,
    revenue_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (minute, product, event_type)
);
CREATE INDEX IF NOT EXISTS rollup_minute_idx ON minute_rollup (minute);
"""


def build_rollups(raw_pattern: str = RAW_PATTERN, db_path: str = DB_PATH) -> dict:
    counts: dict[tuple, int] = defaultdict(int)
    users: dict[tuple, set] = defaultdict(set)
    revenue: dict[tuple, float] = defaultdict(float)
    total = 0
    for path in sorted(glob.glob(raw_pattern)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                event = json.loads(line)
                key = (event["ts"][:16], event["product"], event["event_type"])
                counts[key] += 1
                users[key].add(event["user_id"])
                props = event.get("properties") or {}
                if event["event_type"] == "purchase":
                    revenue[key] += float(props.get("revenue_usd", 0.0))
                total += 1
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(DDL)
    conn.execute("DELETE FROM minute_rollup")
    conn.executemany(
        "INSERT INTO minute_rollup VALUES (?, ?, ?, ?, ?, ?)",
        [(minute, product, etype, counts[key], len(users[key]),
          round(revenue[key], 2))
         for key in sorted(counts)
         for (minute, product, etype) in [key]],
    )
    conn.commit()
    rows = conn.execute("SELECT COUNT(*) FROM minute_rollup").fetchone()[0]
    conn.close()
    return {"events_read": total, "rollup_rows": rows, "db": db_path}


def main() -> None:
    result = build_rollups()
    print(f"aggregated {result['events_read']} events "
          f"into {result['rollup_rows']} rollup rows in {result['db']}")


if __name__ == "__main__":
    main()
