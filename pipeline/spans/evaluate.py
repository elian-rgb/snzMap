"""Eval gate — does the pipeline rediscover Kiki's hand-seeded rows?

This is the gate the plan calls "the real proof" for build order step 4. It exists now,
before there is anything to evaluate, for the same reason `spine/spotcheck.py` existed
before the spine was trusted: a gate written after the fact gets written to pass.

What counts as a hit is spelled out rather than assumed:

  * **Venue** must match on `venue_id`. Falling back to name matching would let a run at
    one Busch Stadium score a hit for the other one.
  * **Operator** must match on `operator_normalized`, so "ARA Services" in a 1993 article
    scores against "Aramark" in the workbook. A sub-brand (Levy) scores against its parent
    (Compass) — same contract, described at two levels.
  * **Start date** must land inside a tolerance set by the GOLD row's own precision. A
    gold row that says "1995, precision=year" cannot demand the pipeline produce March 27.
    Being stricter than the gold data would measure the workbook, not the pipeline.

A hit on venue+operator with a bad date is scored separately as a `date_miss`: the
pipeline found the right run and got the timing wrong, which is a different failure from
never finding it, and lumping them together hides which one is happening.

    .venv/bin/python -m pipeline.spans.evaluate
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from .gold import load_gold

OUT = Path(__file__).resolve().parent.parent / "output"
PIPELINE_TENURE = OUT / "tenure_records.json"

# Days of slack allowed on start_date, keyed by the gold row's stated precision.
TOLERANCE_DAYS = {"exact": 31, "month": 62, "year": 366, "approx": 731}
DEFAULT_TOLERANCE = 366

MIN_GOLD_ROWS = 10          # the plan's floor for a usable eval set
RECALL_TARGET = 0.70        # below this, extraction needs work — not a rounding error


def _date(v: Any) -> dt.date | None:
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _same_run(gold: dict[str, Any], cand: dict[str, Any]) -> bool:
    gv, cv = gold.get("venue_id"), cand.get("venue_id")
    if not gv or not cv or gv != cv:
        return False
    return (gold.get("operator_normalized") or "") == (cand.get("operator_normalized") or "")


def _date_ok(gold: dict[str, Any], cand: dict[str, Any]) -> tuple[bool, str]:
    g, c = _date(gold.get("start_date")), _date(cand.get("start_date"))
    if g is None:
        return True, "gold has no start_date — not scored"
    if c is None:
        return False, "pipeline produced no start_date"
    slack = TOLERANCE_DAYS.get(gold.get("start_precision") or "", DEFAULT_TOLERANCE)
    delta = abs((c - g).days)
    return delta <= slack, f"start_date off by {delta}d (tolerance {slack}d at precision={gold.get('start_precision')})"


def evaluate(pipeline_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gold_rows = [g for g in load_gold()["gold"] if g["verified"]]

    results = []
    for g in gold_rows:
        rec = g["record"]
        matches = [c for c in pipeline_rows if _same_run(rec, c)]
        if not matches:
            results.append({"tenure_id": rec["tenure_id"], "venue_name": rec.get("venue_name"),
                            "operator": rec.get("operator_normalized"), "outcome": "miss",
                            "detail": "no pipeline row for this venue+operator"})
            continue

        scored = [(m, *_date_ok(rec, m)) for m in matches]
        hit = next((s for s in scored if s[1]), None)
        chosen = hit or scored[0]
        results.append({
            "tenure_id": rec["tenure_id"],
            "venue_name": rec.get("venue_name"),
            "operator": rec.get("operator_normalized"),
            "outcome": "hit" if hit else "date_miss",
            "detail": chosen[2],
            "end_status_agrees": rec.get("end_status") == chosen[0].get("end_status"),
            "exit_mode_agrees": (rec.get("exit_mode") or None) == (chosen[0].get("exit_mode") or None),
        })

    hits = [r for r in results if r["outcome"] == "hit"]
    date_misses = [r for r in results if r["outcome"] == "date_miss"]
    return {
        "gold_rows_verified": len(gold_rows),
        "pipeline_rows": len(pipeline_rows),
        "hits": len(hits),
        "date_misses": len(date_misses),
        "misses": len(results) - len(hits) - len(date_misses),
        "recall": round(len(hits) / len(gold_rows), 3) if gold_rows else None,
        "recall_incl_date_misses": round((len(hits) + len(date_misses)) / len(gold_rows), 3) if gold_rows else None,
        "end_status_agreement": sum(1 for r in hits if r["end_status_agrees"]),
        "results": results,
    }


def main() -> int:
    pipeline_rows: list[dict[str, Any]] = []
    if PIPELINE_TENURE.exists():
        pipeline_rows = json.loads(PIPELINE_TENURE.read_text())
    else:
        print(f"no pipeline output yet ({PIPELINE_TENURE.name} missing) — scoring against zero rows")

    report = evaluate(pipeline_rows)
    (OUT / "gold_eval.json").write_text(json.dumps(report, indent=2))

    print(f"verified gold rows : {report['gold_rows_verified']}")
    print(f"pipeline rows      : {report['pipeline_rows']}")
    print(f"hits               : {report['hits']}")
    print(f"date_misses        : {report['date_misses']}  (right run, wrong timing)")
    print(f"misses             : {report['misses']}")
    print(f"recall             : {report['recall']}")

    for r in report["results"]:
        if r["outcome"] != "hit":
            print(f"  {r['outcome'].upper():10} {r['venue_name']} / {r['operator']} — {r['detail']}")

    if report["gold_rows_verified"] < MIN_GOLD_ROWS:
        print(
            f"\nNOT A GATE YET: {report['gold_rows_verified']} verified gold row(s), need "
            f"{MIN_GOLD_ROWS}.\n"
            "  A row counts as verified when its `source` does not say 'verify'. Seeding\n"
            "  and verifying these rows is Kiki's job by design — the eval set has to come\n"
            "  from outside the system it grades, exactly like the MLB list in\n"
            "  spine/spotcheck.py. Passing here on 1 row would mean nothing."
        )
        return 0

    if (report["recall"] or 0) < RECALL_TARGET:
        print(f"\nFAIL: recall {report['recall']} below target {RECALL_TARGET} — extraction needs work.")
        return 1

    print(f"\nPASS: recall {report['recall']} >= {RECALL_TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
