# OpenAI Applied AI Interview: Document Field Extraction

Reported / representative interview solution. Complete runnable Python, standard library only, no installation needed. Python 3.10 or newer.

## Run
```
python3 run_demo.py
python3 extract.py
python3 evaluate.py
```

## Files
- `extract.py` extracts vendor, date, total, tax, currency, document number and line items from receipt text, with a confidence score per field and a human review flag.
- `evaluate.py` runs a built in sample set of six documents and reports field accuracy.
- `run_demo.py` runs extraction plus the evaluation harness and checks the quality bar.

## Design notes
Low confidence or missing total or date sets `needs_review`, so a finance product never books a record it cannot trust. In production the same interface sits behind OCR and a model based extractor, with this rule based path as a fast, auditable baseline and fallback.
