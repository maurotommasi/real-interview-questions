# Metrics Ingestion and Alerting Pipeline

Single file implementation (`metrics_pipeline.py`, Python standard
library only, no dependencies to install) of the design from the Google
Platform Engineer / SRE interview solution: ingestion with a cardinality
guard, a durable write ahead buffer, tiered storage with downsampling, a
query path, and an alert path that is fully separate from the query path.

Companion code for "Real Interview: Platform Engineer / SRE at Google,
design a global metrics and alerting pipeline" by Eng. Mauro Tommasi.

## Run it

```bash
python3 metrics_pipeline.py          # serves on http://127.0.0.1:9090
python3 metrics_pipeline.py --demo   # synthetic traffic, fires an alert
```

## Try it

```bash
curl -s -X POST localhost:9090/ingest -H 'Content-Type: application/json' \
  -d '{"service":"checkout","samples":[{"metric":"http_requests",
       "labels":{"route":"/pay"},"value":12}]}'

curl -s 'localhost:9090/query?metric=http_requests&service=checkout'
curl -s localhost:9090/alerts
curl -s localhost:9090/health
```

## How the pieces map to the design

- **Cardinality guard**: labels are checked against an allow list at
  ingestion. `user_id`, `request_id` and similar labels are rejected with
  a clear error, and each service has a series quota. This is the control
  that stops one bad label from multiplying series by a thousand.
- **Write ahead buffer**: every accepted batch is appended to
  `metrics_wal.jsonl` before it is stored in memory, and replayed on
  startup, so a crash does not silently lose alert inputs. In the global
  design this is the replicated log each region writes to, plus a local
  disk buffer on every host agent.
- **Tiered storage**: raw samples are folded by a compactor into 1 minute
  and 1 hour aggregates (downsampling): 7 days full resolution, 30 days
  at 1 minute, 13 months at 1 hour in the full design.
- **Separate alert path**: the alert engine is its own thread with its
  own state. It evaluates rules on aggregates every `EVAL_INTERVAL_S`
  seconds (2 in this demo, 30 in production) and never shares a lock or
  a queue with the query path, so a dashboard spike cannot delay a page.
- **Alert rules** live in the `RULES` table: name, metric, service,
  window, threshold, severity. Duplicate firings are deduped by rule.

## Scaling notes

This file is the one region, one process core of the design. To scale it
the way the interview answer describes: shard storage by series hash,
partition the log by service and time, run one alert evaluator per
region with a standby, and keep alert state in a small strongly
replicated store.
