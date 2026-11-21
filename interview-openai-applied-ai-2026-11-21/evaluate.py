"""Evaluation harness with a built in sample set.
Compares extracted fields with expected values and reports accuracy.
A field counts as correct when the value matches exactly for text and
dates, and within 0.01 for money amounts.
"""
from extract import extract_fields

CASES = [
    {"text": "Corner Bakery\nInvoice # INV-2041\nDate: 2026-11-18\nCoffee 24.50\nSales tax 3.40\nTotal $45.90",
     "expected": {"vendor": "Corner Bakery", "date": "2026-11-18", "total": 45.90, "tax": 3.40}},
    {"text": "City Office Supplies\nReceipt # REC-8812\n12/03/2026\nPaper 12.00\nPens 8.50\nTotal $20.50",
     "expected": {"vendor": "City Office Supplies", "date": "12/03/2026", "total": 20.50, "tax": 0.0}},
    {"text": "Metro Taxi\nDate: 2026-11-19\nRide 31.20\nTax 2.50\nAmount due $33.70",
     "expected": {"vendor": "Metro Taxi", "date": "2026-11-19", "total": 33.70, "tax": 2.50}},
    {"text": "Hotel Aurora\nInvoice # INV-9920\nDate: 2026-11-20\nRoom 180.00\nVAT 18.00\nGrand total $198.00",
     "expected": {"vendor": "Hotel Aurora", "date": "2026-11-20", "total": 198.00, "tax": 18.00}},
    {"text": "Fresh Market\nDate: 2026-11-21\nGroceries 64.10\nTotal $64.10",
     "expected": {"vendor": "Fresh Market", "date": "2026-11-21", "total": 64.10, "tax": 0.0}},
    {"text": "Cloud Hosting Co\nInvoice # INV-5510\nDate: 2026-11-15\nHosting 99.00\nSales tax 7.92\nTotal $106.92",
     "expected": {"vendor": "Cloud Hosting Co", "date": "2026-11-15", "total": 106.92, "tax": 7.92}},
]

def _match(field_name, got, want):
    if isinstance(want, float):
        return got is not None and abs(float(got) - want) < 0.01
    return got == want

def run_evaluation(cases=CASES):
    total_fields = 0
    correct = 0
    per_field = {}
    review_count = 0
    for case in cases:
        result = extract_fields(case["text"]).to_dict()
        if result["needs_review"]:
            review_count += 1
        for name, want in case["expected"].items():
            total_fields += 1
            ok = _match(name, result.get(name), want)
            per_field.setdefault(name, [0, 0])
            per_field[name][1] += 1
            if ok:
                correct += 1
                per_field[name][0] += 1
    accuracy = correct / total_fields if total_fields else 0.0
    return {"cases": len(cases), "fields": total_fields, "correct": correct,
            "accuracy": round(accuracy, 4), "per_field": per_field,
            "needs_review": review_count}

if __name__ == "__main__":
    report = run_evaluation()
    print(f"Cases: {report['cases']}  Fields: {report['fields']}  Correct: {report['correct']}")
    print(f"Field accuracy: {report['accuracy']:.2%}")
    for name, (ok, n) in sorted(report["per_field"].items()):
        print(f"  {name}: {ok}/{n}")
    print(f"Flagged for review: {report['needs_review']}")
