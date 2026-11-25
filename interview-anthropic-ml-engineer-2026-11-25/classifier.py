"""Production safety classifier pipeline, interview solution.

Trains a multinomial Naive Bayes text classifier that flags
policy violating prompts, evaluates it with precision, recall
and F1 at several thresholds, picks a threshold under a recall
floor, and serves predictions with a drift check.
Standard library only.
"""
import hashlib
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


@dataclass
class Example:
    example_id: str
    text: str
    label: int  # 1 = violating, 0 = allowed
    source: str = "labelled_set"


@dataclass
class Prediction:
    example_id: str
    score: float
    flagged: bool
    top_terms: list


@dataclass
class EvalReport:
    threshold: float
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float


class NaiveBayesClassifier:
    """Multinomial Naive Bayes over word counts, Laplace smoothing."""

    def __init__(self, alpha=1.0):
        self.alpha = alpha
        self.vocab = set()
        self.counts = {0: Counter(), 1: Counter()}
        self.totals = {0: 0, 1: 0}
        self.docs = {0: 0, 1: 0}
        self.total_docs = 0

    def train(self, examples):
        for ex in examples:
            tokens = tokenize(ex.text)
            self.docs[ex.label] += 1
            self.total_docs += 1
            for tok in tokens:
                self.vocab.add(tok)
                self.counts[ex.label][tok] += 1
                self.totals[ex.label] += 1
        return self

    def _log_prob(self, tokens, label):
        prior = math.log(self.docs[label] / max(1, self.total_docs))
        denom = self.totals[label] + self.alpha * max(1, len(self.vocab))
        score = prior
        for tok in tokens:
            num = self.counts[label].get(tok, 0) + self.alpha
            score += math.log(num / denom)
        return score

    def predict_score(self, text):
        tokens = tokenize(text)
        log0 = self._log_prob(tokens, 0)
        log1 = self._log_prob(tokens, 1)
        # Convert the log odds gap to a probability in 0..1.
        gap = max(-30.0, min(30.0, log1 - log0))
        return 1.0 / (1.0 + math.exp(-gap))

    def predict(self, example_id, text, threshold=0.5):
        tokens = tokenize(text)
        score = self.predict_score(text)
        # Explain: terms that push hardest toward the violating class.
        scored = []
        for tok in set(tokens):
            push = (self.counts[1].get(tok, 0) + self.alpha) / (
                self.counts[0].get(tok, 0) + self.alpha)
            scored.append((math.log(push), tok))
        scored.sort(reverse=True)
        top = [tok for _, tok in scored[:3] if _ > 0]
        return Prediction(example_id, round(score, 4),
                          score >= threshold, top)


def evaluate(model, examples, threshold):
    tp = fp = tn = fn = 0
    for ex in examples:
        pred = model.predict(ex.example_id, ex.text, threshold)
        if pred.flagged and ex.label == 1:
            tp += 1
        elif pred.flagged and ex.label == 0:
            fp += 1
        elif not pred.flagged and ex.label == 0:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return EvalReport(threshold, tp, fp, tn, fn,
                      round(precision, 4), round(recall, 4), round(f1, 4))


def pick_threshold(model, examples, thresholds, recall_floor=0.80):
    """Pick the threshold with best F1 among those meeting the floor."""
    reports = [evaluate(model, examples, t) for t in thresholds]
    ok = [r for r in reports if r.recall >= recall_floor]
    pool = ok if ok else reports
    best = max(pool, key=lambda r: r.f1)
    return best, reports


@dataclass
class ServingLog:
    events: list = field(default_factory=list)

    def record(self, pred, latency_ms):
        digest = hashlib.sha256(pred.example_id.encode()).hexdigest()[:8]
        self.events.append({
            "ts": time.time(), "id_hash": digest,
            "score": pred.score, "flagged": pred.flagged,
            "latency_ms": round(latency_ms, 3),
            "top_terms": pred.top_terms,
        })

    def drift_check(self, recent_scores, baseline_mean=0.20, limit=0.15):
        if not recent_scores:
            return {"drift": False, "recent_mean": 0.0}
        mean = sum(recent_scores) / len(recent_scores)
        return {"drift": abs(mean - baseline_mean) > limit,
                "recent_mean": round(mean, 4)}


def serve(model, items, threshold, log):
    """Serve a batch, items are (example_id, text) pairs."""
    out = []
    for example_id, text in items:
        start = time.perf_counter()
        pred = model.predict(example_id, text, threshold)
        latency = (time.perf_counter() - start) * 1000.0
        log.record(pred, latency)
        out.append(pred)
    return out
