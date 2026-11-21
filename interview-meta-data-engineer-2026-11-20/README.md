# Clickstream Analytics Pipeline (Meta Data Engineer Interview)

Companion code for the LinkedIn Real Interview post "Data Engineer at
Meta: a clickstream pipeline for near real-time product analytics"
by Eng. Mauro Tommasi (20 Nov 2026). The interview question is a
reported / representative question based on publicly reported Meta
data engineering interviews. It is not a leaked question.
Follow along on LinkedIn: linkedin.com/in/maurotommasi

A complete, runnable local implementation of the core pipeline:
event producer, validated ingestion, partitioned raw storage,
minute rollup aggregation, and a query API for dashboards.
Python standard library only, nothing to install.

## Run the demo (one process, about 5 seconds)

```bash
python3 run_demo.py
```

It generates 20,000 events, ingests them (one duplicate and one
broken event are added on purpose and handled), builds rollups,
and prints the funnel and summary the dashboards would show.
All counts are asserted, so a green run means the stages agree.

## Run it as services

```bash
python3 ingest.py --port 8090
python3 producer.py --count 20000 --url http://localhost:8090/events
python3 aggregate.py
python3 query.py --port 8091
curl "http://localhost:8091/api/summary"
curl "http://localhost:8091/api/funnel"
curl "http://localhost:8091/api/timeseries?event_type=purchase"
curl "http://localhost:8091/api/top-pages"
```

## How it maps to the production design

| Local piece | Production equivalent at scale |
| --- | --- |
| producer.py | Web, iOS and Android clients and backends |
| ingest.py collectors | Stateless collectors behind a load balancer |
| JSONL hour partitions | Kafka topics, then Parquet files in a data lake |
| aggregate.py | Flink or Spark streaming job, plus batch backfill |
| SQLite rollups | A serving store such as Druid, Pinot or ClickHouse |
| query.py | The dashboard API with caching and per team quotas |

## Layout

- `events.py` event schema, validation, realistic event generator
- `producer.py` generates events to a file or to the ingestion API
- `ingest.py` validation, dedupe by event_id, hour partitioned storage
- `aggregate.py` raw events to one minute rollups in SQLite
- `query.py` dashboard API: summary, funnel, timeseries, top pages
- `run_demo.py` end to end run with assertions
