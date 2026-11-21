"""Ingestion service.

Accepts batches of events over HTTP, validates every event against
the schema, deduplicates by event_id, and appends valid events to
hour partitioned JSONL files under data/raw/YYYY-MM-DD/HH.jsonl.
Invalid events go to data/rejected/YYYY-MM-DD.jsonl with the reason,
so producers can see and fix what was dropped.

In the production design this maps to a load balancer in front of
stateless collectors writing to Kafka. The contract is identical:
validate, dedupe, partition by time, never lose an accepted event.

Run:  python ingest.py --port 8090
Send: python producer.py --count 20000 --url http://localhost:8090/events
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from events import validate_event

RAW_DIR = os.path.join("data", "raw")
REJECTED_DIR = os.path.join("data", "rejected")
_seen_ids: set[str] = set()


def _append(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def ingest_events(events: list[dict]) -> dict:
    """Validate, dedupe and store a batch. Returns counts."""
    accepted: list[dict] = []
    rejected: list[dict] = []
    duplicates = 0
    for event in events:
        problems = validate_event(event)
        if problems:
            rejected.append({"event": event, "problems": problems})
            continue
        if event["event_id"] in _seen_ids:
            duplicates += 1
            continue
        _seen_ids.add(event["event_id"])
        accepted.append(event)
    by_partition: dict[str, list[dict]] = {}
    for event in accepted:
        day, hour = event["ts"][:10], event["ts"][11:13]
        by_partition.setdefault(os.path.join(RAW_DIR, day, f"{hour}.jsonl"),
                                []).append(event)
    for path, rows in by_partition.items():
        _append(path, rows)
    if rejected:
        day = rejected[0]["event"].get("ts", "unknown")[:10] \
            if isinstance(rejected[0]["event"], dict) else "unknown"
        _append(os.path.join(REJECTED_DIR, f"{day}.jsonl"), rejected)
    return {"accepted": len(accepted), "rejected": len(rejected),
            "duplicates": duplicates}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console quiet
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
        else:
            body = json.dumps({"error": "not found"}).encode()
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/events":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"[]")
            events = payload["events"] if isinstance(payload, dict) else payload
            result = ingest_events(events)
            status, body = 200, json.dumps(result).encode()
        except (ValueError, KeyError, TypeError) as exc:
            status = 400
            body = json.dumps({"error": f"bad request: {exc}"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"ingestion listening on port {args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
