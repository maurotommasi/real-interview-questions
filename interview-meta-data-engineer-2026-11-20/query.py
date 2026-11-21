"""Query layer: the API the dashboards call.

Reads only the SQLite rollups, never the raw events, so dashboard
queries stay fast and cheap no matter how large the raw data grows.
That separation is the core of the design: raw is for reprocessing,
rollups are for serving.

Run:  python query.py --port 8091
Try:  curl "http://localhost:8091/api/summary"
      curl "http://localhost:8091/api/funnel"
      curl "http://localhost:8091/api/timeseries?event_type=purchase"
      curl "http://localhost:8091/api/top-pages"
"""
import argparse
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.path.join("data", "rollups.db")
FUNNEL = ["page_view", "click", "add_to_cart", "checkout_start", "purchase"]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def summary() -> dict:
    conn = _db()
    row = conn.execute(
        "SELECT COALESCE(SUM(events),0) AS events, "
        "COALESCE(SUM(revenue_usd),0) AS revenue FROM minute_rollup"
    ).fetchone()
    per_type = {r["event_type"]: r["n"] for r in conn.execute(
        "SELECT event_type, SUM(events) AS n FROM minute_rollup "
        "GROUP BY event_type")}
    conn.close()
    return {"total_events": row["events"],
            "revenue_usd": round(row["revenue"], 2), "by_type": per_type}


def timeseries(event_type: str = "page_view", product: str = "") -> list[dict]:
    conn = _db()
    sql = ("SELECT minute, SUM(events) AS events, SUM(users) AS users "
           "FROM minute_rollup WHERE event_type = ?")
    params: list = [event_type]
    if product:
        sql += " AND product = ?"
        params.append(product)
    sql += " GROUP BY minute ORDER BY minute"
    rows = [dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return rows


def funnel() -> list[dict]:
    conn = _db()
    rows = {r["event_type"]: r["n"] for r in conn.execute(
        "SELECT event_type, SUM(events) AS n FROM minute_rollup "
        "GROUP BY event_type")}
    conn.close()
    first = rows.get(FUNNEL[0], 0) or 1
    return [{"step": step, "events": rows.get(step, 0),
             "pct_of_first": round(100.0 * rows.get(step, 0) / first, 2)}
            for step in FUNNEL]


def top_pages(limit: int = 5) -> list[dict]:
    """Top pages by views. Page level detail lives in a page rollup
    in the full design; locally we read it from the raw partitions
    for the most recent hour only, which stays small."""
    import glob
    from collections import Counter
    files = sorted(glob.glob(os.path.join("data", "raw", "*", "*.jsonl")))
    if not files:
        return []
    counts: Counter = Counter()
    with open(files[-1], encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event["event_type"] == "page_view":
                counts[event["page"]] += 1
    return [{"page": page, "views": n} for page, n in counts.most_common(limit)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        routes = {"/api/summary": lambda: summary(),
                  "/api/funnel": lambda: funnel(),
                  "/api/top-pages": lambda: top_pages(),
                  "/api/timeseries": lambda: timeseries(
                      params.get("event_type", ["page_view"])[0],
                      params.get("product", [""])[0]),
                  "/health": lambda: {"status": "ok"}}
        fn = routes.get(parsed.path)
        if fn is None:
            status, payload = 404, {"error": "not found"}
        else:
            try:
                status, payload = 200, fn()
            except sqlite3.OperationalError:
                status, payload = 503, {"error": "rollups not built yet, run aggregate.py"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"query layer listening on port {args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
