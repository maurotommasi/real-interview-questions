"""
Citation grounding checker and release gate for an AI answer engine.

Interview piece: Perplexity, Applied AI Engineer (reported, representative).
Saturday 28 November 2026.

The problem in plain terms: an answer engine writes answers with citations.
Before a new model version ships, someone has to prove the citations actually
support the claims, at scale, without a human reading every answer. This file
is that proof pipeline in miniature:

  1. Score every claim against the text of the source it cites.
  2. Label each claim supported, weak or unsupported.
  3. Roll the labels up into a release gate: ship, or do not ship.

Standard library only. Run it:  python3 citation_check.py
It prints a report on a small built-in eval set and checks its own results.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "as", "at", "by",
    "from", "that", "this", "than", "then", "so", "such", "into", "over",
    "per", "about", "after", "before", "between", "during",
}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def content_tokens(text: str) -> list[str]:
    """Lowercase word and number tokens with stopwords removed.

    Numbers keep their decimal point (for example 3.5) because in an eval set
    a wrong number is exactly the failure we are hunting for.
    """
    raw = TOKEN_RE.findall(text.lower())
    return [t for t in raw if t not in STOPWORDS]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SUPPORTED_AT = 0.60   # at least 60 percent of claim content tokens in source
WEAK_AT = 0.35        # between 35 and 60 percent: partial support


def support_score(claim: str, source_text: str) -> float:
    """Fraction of the claim's content tokens that appear in the source.

    One hard rule sits on top of the fraction: numbers are facts. If the
    claim states a number that the source never states, the claim is
    unsupported no matter how many other words overlap. That rule exists
    because the classic production failure is a fluent sentence carrying
    one invented figure, and plain token overlap waves it through.

    Token containment is still a blunt instrument: it is fast, it is
    explainable to a product manager in one sentence, and it catches
    claims the cited page never made. It does not understand paraphrase;
    the PDF is honest about that limit.
    """
    claim_tokens = content_tokens(claim)
    if not claim_tokens:
        return 0.0
    source_set = set(content_tokens(source_text))
    claim_numbers = [t for t in claim_tokens if any(ch.isdigit() for ch in t)]
    if any(n not in source_set for n in claim_numbers):
        return 0.0
    hits = sum(1 for t in claim_tokens if t in source_set)
    return hits / len(claim_tokens)


def label_for(score: float) -> str:
    if score >= SUPPORTED_AT:
        return "supported"
    if score >= WEAK_AT:
        return "weak"
    return "unsupported"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClaimResult:
    claim: str
    source_id: str
    score: float
    label: str


@dataclass
class AnswerResult:
    answer_id: str
    claims: list[ClaimResult] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        """An answer counts as grounded when no claim is unsupported."""
        return all(c.label != "unsupported" for c in self.claims)


def check_answer(answer_id: str, claims: list[tuple[str, str]],
                 sources: dict[str, str]) -> AnswerResult:
    """claims is a list of (claim text, source id) pairs."""
    result = AnswerResult(answer_id=answer_id)
    for claim_text, source_id in claims:
        source_text = sources.get(source_id, "")
        score = support_score(claim_text, source_text)
        result.claims.append(ClaimResult(
            claim=claim_text, source_id=source_id,
            score=round(score, 3), label=label_for(score)))
    return result


# ---------------------------------------------------------------------------
# Release gate
# ---------------------------------------------------------------------------

@dataclass
class GatePolicy:
    max_unsupported_rate: float = 0.05   # at most 5 percent of claims
    min_grounded_rate: float = 0.90     # at least 90 percent of answers


@dataclass
class GateReport:
    total_claims: int
    supported: int
    weak: int
    unsupported: int
    grounded_answers: int
    total_answers: int
    ship: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def unsupported_rate(self) -> float:
        return self.unsupported / self.total_claims if self.total_claims else 0.0

    @property
    def grounded_rate(self) -> float:
        return self.grounded_answers / self.total_answers if self.total_answers else 0.0


def release_gate(results: list[AnswerResult], policy: GatePolicy) -> GateReport:
    claims = [c for r in results for c in r.claims]
    report = GateReport(
        total_claims=len(claims),
        supported=sum(1 for c in claims if c.label == "supported"),
        weak=sum(1 for c in claims if c.label == "weak"),
        unsupported=sum(1 for c in claims if c.label == "unsupported"),
        grounded_answers=sum(1 for r in results if r.grounded),
        total_answers=len(results),
        ship=True,
    )
    if report.unsupported_rate > policy.max_unsupported_rate:
        report.ship = False
        report.reasons.append(
            f"unsupported rate {report.unsupported_rate:.1%} is above the "
            f"{policy.max_unsupported_rate:.0%} limit")
    if report.grounded_rate < policy.min_grounded_rate:
        report.ship = False
        report.reasons.append(
            f"grounded answer rate {report.grounded_rate:.1%} is below the "
            f"{policy.min_grounded_rate:.0%} floor")
    if report.ship:
        report.reasons.append("all thresholds passed")
    return report


# ---------------------------------------------------------------------------
# Built-in eval set: six claims over three answers, written so the expected
# labels are known in advance. This is the part an interviewer probes: the
# set contains one invented number and one claim its source never made.
# ---------------------------------------------------------------------------

SOURCES = {
    "S1": ("The city council approved the budget on Tuesday. The budget sets "
           "aside 4.2 million dollars for road repairs in 2027 and 1.1 "
           "million dollars for the public library system."),
    "S2": ("The trial enrolled 214 patients across six hospitals. After "
           "twelve weeks, the treatment group showed a 31 percent reduction "
           "in symptoms compared with the control group."),
    "S3": ("Version 2.0 of the library ships with a new streaming API. The "
           "release notes list breaking changes in the configuration file "
           "format and drop support for Python 3.8."),
}

ANSWERS = [
    ("A1", [
        ("The budget sets aside 4.2 million dollars for road repairs in 2027", "S1"),
        ("The budget funds road repairs, libraries and parks across the city", "S1"),
    ]),
    ("A2", [
        ("The trial enrolled 214 patients across six hospitals", "S2"),
        ("Symptoms fell by 58 percent after twelve weeks", "S2"),
    ]),
    ("A3", [
        ("Version 2.0 drops support for Python 3.8", "S3"),
        ("The streaming API guarantees exactly once delivery", "S3"),
    ]),
]

EXPECTED_LABELS = ["supported", "weak", "supported",
                   "unsupported", "supported", "unsupported"]


def main() -> int:
    results = [check_answer(aid, claims, SOURCES) for aid, claims in ANSWERS]

    print("Claim by claim")
    print("-" * 72)
    flat = []
    for r in results:
        for c in r.claims:
            flat.append(c.label)
            print(f"{r.answer_id}  [{c.label:11s}] score {c.score:.3f}  "
                  f"({c.source_id}) {c.claim}")
    print("-" * 72)

    gate = release_gate(results, GatePolicy())
    print(f"Claims: {gate.total_claims} total, {gate.supported} supported, "
          f"{gate.weak} weak, {gate.unsupported} unsupported")
    print(f"Answers grounded: {gate.grounded_answers} of {gate.total_answers} "
          f"({gate.grounded_rate:.1%})")
    print(f"Unsupported rate: {gate.unsupported_rate:.1%} "
          f"(limit {GatePolicy().max_unsupported_rate:.0%})")
    print(f"Gate decision: {'SHIP' if gate.ship else 'DO NOT SHIP'}")
    for reason in gate.reasons:
        print(f"  - {reason}")

    # Self-checks: the demo is only useful if it proves itself.
    assert flat == EXPECTED_LABELS, f"label mismatch: {flat}"
    assert gate.total_claims == 6 and gate.supported == 3
    assert gate.weak == 1 and gate.unsupported == 2
    assert gate.grounded_answers == 1 and gate.total_answers == 3
    assert gate.ship is False, "this eval set must fail the gate on purpose"
    print("Self-checks passed: labels, counts and the no-ship decision match "
          "the expected values.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
