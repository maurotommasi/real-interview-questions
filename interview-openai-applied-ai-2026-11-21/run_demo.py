"""CLI demo: extract from samples, then run the evaluation harness."""
import json
from extract import SAMPLE, extract_fields
from evaluate import run_evaluation

def main():
    print("=== Extraction demo ===")
    result = extract_fields(SAMPLE)
    print(json.dumps(result.to_dict(), indent=2))
    print(f"Overall confidence: {result.overall_confidence:.2f}")
    print(f"Needs human review: {result.needs_review}")
    print()
    print("=== Evaluation harness ===")
    report = run_evaluation()
    print(f"Cases: {report['cases']}  Fields: {report['fields']}  Correct: {report['correct']}")
    print(f"Field accuracy: {report['accuracy']:.2%}")
    for name, (ok, n) in sorted(report["per_field"].items()):
        print(f"  {name}: {ok}/{n}")
    print(f"Flagged for review: {report['needs_review']}")
    print("Quality bar check: accuracy >= 0.90 ->", report["accuracy"] >= 0.90)

if __name__ == "__main__":
    main()
