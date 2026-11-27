# Netflix Data Engineer Interview, Sessionization (27 Nov 2026)

Reported and representative interview question, based on publicly reported candidate experiences, not a leaked or exact confidential question.

Question: given a play_events table, group play events into viewing sessions with a 30 minute inactivity gap, returning start, end, watch time and completion.

Files: sessionize.py (complete, runnable, standard library only, run: python3 sessionize.py) and sessionize.sql (the same logic with LAG, a new session flag and a running sum). The full worked solution is in the PDF in this folder once uploaded by the publishing run.
