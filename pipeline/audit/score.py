"""Read the filled-in audit sample back and turn it into a precision number.

Reports an interval, not just a fraction. At n=20 a point estimate is close to meaningless
on its own: 18 correct out of 20 is "90%", but the honest reading is "somewhere between 70%
and 97%, and we cannot tell where". Publishing the bare 90% would be a wrong big number of
exactly the kind this project exists to avoid. The Wilson interval is used rather than the
textbook normal one because the normal approximation misbehaves badly at small n and near
1.0 — it happily reports upper bounds above 100%.

`cant_tell` rows are excluded from the denominator and reported separately. Counting them
as correct would inflate the number; counting them as wrong would punish the extractor for
a short excerpt. Neither is a measurement.

    .venv/bin/python -m pipeline.audit.score
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .sample import SAMPLE_OUT, VERDICTS

OUT = Path(__file__).resolve().parent.parent / "output"
SUMMARY_OUT = OUT / "audit_summary.json"

# Below this the interval is so wide that quoting a precision figure misleads more than it
# informs. The rows still print; the summary just refuses to call itself a measurement.
MIN_JUDGED = 15

FAILURE_MODES = [k for k in VERDICTS if k not in ("correct", "cant_tell")]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _cut(rows: list[dict[str, Any]], field: str, value: str) -> dict[str, Any]:
    sub = [r for r in rows if r.get(field) == value]
    judged = [r for r in sub if r["verdict"] in VERDICTS and r["verdict"] != "cant_tell"]
    correct = [r for r in judged if r["verdict"] == "correct"]
    lo, hi = wilson(len(correct), len(judged))
    return {
        "rows": len(sub),
        "judged": len(judged),
        "correct": len(correct),
        "precision": round(len(correct) / len(judged), 3) if judged else None,
        "ci95": [round(lo, 3), round(hi, 3)] if judged else None,
    }


def score(rows: list[dict[str, Any]], auditor: str = "unrecorded") -> dict[str, Any]:
    verdicts = Counter((r.get("verdict") or "").strip() for r in rows)
    unrecognised = {v: n for v, n in verdicts.items() if v and v not in VERDICTS}

    filled = [r for r in rows if (r.get("verdict") or "").strip() in VERDICTS]
    for r in filled:
        r["verdict"] = r["verdict"].strip()
    judged = [r for r in filled if r["verdict"] != "cant_tell"]
    correct = [r for r in judged if r["verdict"] == "correct"]
    lo, hi = wilson(len(correct), len(judged))

    return {
        "auditor": auditor,
        # An audit run by whoever built the extractor is weaker evidence than an
        # independent one, and the file should say so rather than let a reader assume.
        "independent": auditor not in ("unrecorded", "pipeline-author"),
        "sample_rows": len(rows),
        "verdicts_filled": len(filled),
        "unfilled": len(rows) - len(filled) - sum(unrecognised.values()),
        "unrecognised_verdicts": unrecognised,
        "cant_tell": sum(1 for r in filled if r["verdict"] == "cant_tell"),
        "judged": len(judged),
        "correct": len(correct),
        "precision": round(len(correct) / len(judged), 3) if judged else None,
        "ci95": [round(lo, 3), round(hi, 3)] if judged else None,
        "is_a_measurement": len(judged) >= MIN_JUDGED,
        "failure_modes": {m: sum(1 for r in judged if r["verdict"] == m)
                          for m in FAILURE_MODES if any(r["verdict"] == m for r in judged)},
        "by_pipeline_flag": {
            "flagged": _cut(filled, "pipeline_flagged_it", "yes"),
            "not_flagged": _cut(filled, "pipeline_flagged_it", "no"),
        },
        "by_map_presence": {
            "on_the_map": _cut(filled, "on_the_map", "yes"),
            "off_the_map": _cut(filled, "on_the_map", "no"),
        },
        "wrong_rows": [
            {"event_id": r.get("event_id"), "verdict": r["verdict"],
             "claim": r.get("claim"), "note": r.get("auditor_note")}
            for r in judged if r["verdict"] != "correct"
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--auditor", default="unrecorded",
                    help="who judged the rows. 'pipeline-author' marks the result as "
                         "not independent.")
    args = ap.parse_args()

    if not SAMPLE_OUT.exists():
        print(f"no {SAMPLE_OUT.name} — run: .venv/bin/python -m pipeline.audit.sample")
        return 1

    with SAMPLE_OUT.open() as fh:
        rows = list(csv.DictReader(fh))

    report = score(rows, args.auditor)
    SUMMARY_OUT.write_text(json.dumps(report, indent=2))

    print(f"sample rows      : {report['sample_rows']}")
    print(f"verdicts filled  : {report['verdicts_filled']}  (unfilled {report['unfilled']})")
    print(f"cant_tell        : {report['cant_tell']}  (excluded from the denominator)")
    print(f"judged           : {report['judged']}")
    print(f"correct          : {report['correct']}")

    if report["unrecognised_verdicts"]:
        print("\nUNRECOGNISED VERDICTS — these were not counted:")
        for v, n in report["unrecognised_verdicts"].items():
            print(f"  {v!r} x{n}")
        print("  allowed: " + ", ".join(VERDICTS))

    if report["precision"] is not None:
        lo, hi = report["ci95"]
        print(f"\nprecision        : {report['precision']:.0%}  "
              f"(95% CI {lo:.0%}\u2013{hi:.0%}, n={report['judged']})")

    if report["failure_modes"]:
        print("\nhow it went wrong:")
        for m, n in sorted(report["failure_modes"].items(), key=lambda x: -x[1]):
            print(f"  {m:18} {n}   {VERDICTS[m]}")

    flag = report["by_pipeline_flag"]
    if flag["flagged"]["judged"] and flag["not_flagged"]["judged"]:
        print(f"\ndoes needs_review predict errors?")
        print(f"  flagged      {flag['flagged']['correct']}/{flag['flagged']['judged']} correct")
        print(f"  not flagged  {flag['not_flagged']['correct']}/{flag['not_flagged']['judged']} correct")

    if not report["independent"]:
        print("\nNOT INDEPENDENT: judged by the pipeline's own author. Every row carries the\n"
              "  excerpt it was judged on, so any of these verdicts can be re-checked in\n"
              "  seconds — but a second reader would make this a stronger claim.")

    if not report["is_a_measurement"]:
        print(
            f"\nNOT A MEASUREMENT YET: {report['judged']} judged row(s), need {MIN_JUDGED}.\n"
            "  The interval below that width is too wide to quote — say 'unaudited' rather\n"
            "  than publishing a precision figure the sample cannot support."
        )
        return 0

    print(f"\nwrote {SUMMARY_OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
