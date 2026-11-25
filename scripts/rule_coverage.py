"""Measure how many realistic merchant descriptions the rules alone place, and how many correctly.

Run:  python scripts/rule_coverage.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.categorize import NEEDS_REVIEW, rule_category  # noqa: E402

rows = list(csv.DictReader(open(Path(__file__).resolve().parent.parent / "tests" / "merchant_samples.csv")))
placed = right = 0
for r in rows:
    got = rule_category(r["Description"], -10.0)
    if got != NEEDS_REVIEW:
        placed += 1
        if got == r["Expected"]:
            right += 1
        else:
            print(f"WRONG   {r['Description']!r}: got {got}, expected {r['Expected']}")
    else:
        print(f"MISSED  {r['Description']!r} (expected {r['Expected']})")
n = len(rows)
print(f"\n{n} merchants | placed by rules: {placed} ({placed / n:.0%}) | "
      f"correct: {right} ({right / n:.0%} of all, {right / max(placed, 1):.0%} of placed)")
