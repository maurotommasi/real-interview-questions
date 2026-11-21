"""Receipt and document field extraction with confidence scoring.
Standard library only. Input is plain text from OCR or a document.
Output is a structured record a finance product can store and audit.
"""
import re
from dataclasses import dataclass, field

MONEY = re.compile(r"(?P<cur>USD|EUR|GBP|\$|€|£)?\s*(?P<amt>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})")
DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2}|\d{1,2} [A-Z][a-z]{2} 20\d{2})\b")
TOTAL_WORDS = ("total", "amount due", "balance due", "grand total")
TAX_WORDS = ("tax", "vat", "sales tax")
INVOICE = re.compile(r"(?:invoice|inv|receipt)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z0-9\-]{4,})", re.I)

@dataclass
class Field:
    name: str
    value: object
    confidence: float
    source_line: str = ""

@dataclass
class Extraction:
    vendor: Field
    date: Field
    total: Field
    tax: Field
    currency: Field
    document_number: Field
    line_items: list = field(default_factory=list)
    overall_confidence: float = 0.0
    needs_review: bool = False

    def to_dict(self):
        return {
            "vendor": self.vendor.value, "date": self.date.value,
            "total": self.total.value, "tax": self.tax.value,
            "currency": self.currency.value,
            "document_number": self.document_number.value,
            "line_items": self.line_items,
            "overall_confidence": round(self.overall_confidence, 3),
            "needs_review": self.needs_review,
        }

def _money_on_line(line):
    m = MONEY.search(line.replace(" ", " "))
    if not m:
        return None, None
    amt = float(m.group("amt").replace(",", ""))
    cur = m.group("cur") or ""
    cur = {"$": "USD", "€": "EUR", "£": "GBP"}.get(cur, cur or None)
    return amt, cur

def _find_labelled(lines, words):
    best = None
    for line in lines:
        low = line.lower()
        if any(w in low for w in words):
            amt, cur = _money_on_line(line)
            if amt is not None:
                conf = 0.95 if "total" in low or "amount due" in low else 0.85
                best = (amt, cur, conf, line.strip())
    return best

def extract_fields(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty document text")
    vendor_raw = lines[0].strip()
    vendor = Field("vendor", vendor_raw, 0.9 if len(vendor_raw) >= 3 else 0.4, vendor_raw)
    date_f = Field("date", None, 0.0)
    for line in lines:
        m = DATE.search(line)
        if m:
            date_f = Field("date", m.group(1), 0.92, line.strip())
            break
    total_found = _find_labelled(lines, TOTAL_WORDS)
    if total_found:
        amt, cur, conf, src = total_found
        total = Field("total", amt, conf, src)
        currency = Field("currency", cur or "USD", 0.9 if cur else 0.6, src)
    else:
        amounts = [_money_on_line(ln) for ln in lines]
        amounts = [(a, c) for a, c in amounts if a is not None]
        if amounts:
            amt, cur = max(amounts, key=lambda x: x[0])
            total = Field("total", amt, 0.55, "largest amount fallback")
            currency = Field("currency", cur or "USD", 0.5)
        else:
            total = Field("total", None, 0.0)
            currency = Field("currency", None, 0.0)
    tax_found = _find_labelled(lines, TAX_WORDS)
    if tax_found:
        amt, cur, conf, src = tax_found
        tax = Field("tax", amt, conf, src)
    else:
        tax = Field("tax", 0.0, 0.65, "no tax line found, assumed zero")
    doc_f = Field("document_number", None, 0.0)
    m = INVOICE.search(text)
    if m:
        doc_f = Field("document_number", m.group(1), 0.88, m.group(0))
    items = []
    for line in lines:
        amt, cur = _money_on_line(line)
        low = line.lower()
        if amt is not None and not any(w in low for w in TOTAL_WORDS + TAX_WORDS):
            name = MONEY.sub("", line).strip(" -:")
            if len(name) >= 3:
                items.append({"name": name[:60], "amount": amt})
    scores = [vendor.confidence, date_f.confidence, total.confidence, tax.confidence]
    overall = sum(scores) / len(scores)
    needs_review = overall < 0.75 or total.value is None or date_f.value is None
    return Extraction(vendor, date_f, total, tax, currency, doc_f, items, overall, needs_review)

SAMPLE = """Corner Bakery
Invoice # INV-2041
Date: 2026-11-18
Coffee beans 1kg  24.50
Oat milk 6 pack  18.00
Sales tax  3.40
Total  $45.90
Thank you"""

if __name__ == "__main__":
    import json
    print(json.dumps(extract_fields(SAMPLE).to_dict(), indent=2))
