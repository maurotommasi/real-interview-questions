# Real Interview: Perplexity, Applied AI Engineer (28 Nov 2026)

Reported and representative interview question: build the citation
grounding check that decides whether a new answer model is safe to ship.

`citation_check.py` scores every claim in an answer against the text of
the source it cites (token containment plus a hard rule: an invented
number zeroes the score), labels claims supported, weak or unsupported,
and rolls the labels into a release gate with thresholds set in advance.

Run it (standard library only):

    python3 citation_check.py

On the built-in six claim eval set it prints scores of 1.00, 0.50, 1.00,
0.00, 0.83 and 0.33, counts 3 supported, 1 weak and 2 unsupported, and
the gate decides DO NOT SHIP, with the reasons printed. The script
asserts its own expected results before exiting.
