# Interview: Google, System Design for AI Roles, 2026-11-22

Reported / representative interview question, based on publicly reported
interviews, not a leaked or exact confidential question.

Question: design a real time AI inference platform that serves 100 million
requests per day across chat, classification, extraction and reasoning tasks,
with a p95 latency budget, per tenant rate limits, a cost budget per request,
and safe behaviour when a model fails.

## Files
- gateway.py: the serving core. Request validation types, per tenant token
  bucket rate limiting, an exact response cache, model routing by task,
  quality floor and budget, a circuit breaker per model, retry and fallback,
  latency and cost accounting, and a Little's law capacity estimator.
- run_demo.py: runs five requests, a duplicate that hits the cache, a failure
  drill that forces the small model to fail and falls back, then prints the
  capacity estimate and stats.

## Run
python3 run_demo.py

Python standard library only, no installs, no API keys, no network.
Models are simulated locally and deterministically.
