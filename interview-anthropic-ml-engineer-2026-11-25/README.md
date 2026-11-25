# Anthropic, ML Engineer, interview code, 2026-11-25

Design, train and evaluate a production safety classifier for incoming prompts. Reported, representative interview question, not a leaked question. Complete runnable code, Python standard library only.

Run: python3 run_demo.py

Verified run: vocab size 72, train docs 16. Held out set at thresholds 0.3, 0.5 and 0.7 gives precision 0.75, recall 1.0, F1 0.8571, chosen threshold 0.3. Serving flags s1 at 0.9647 and s3 at 0.9867, allows s2 at 0.0282, 3 serving events logged.
