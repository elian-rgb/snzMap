"""Write the three federal outputs the console and the humans read.

Three outputs because the federal data answers two different questions and owes an account
of a third:

  federal_venue_awards.geojson — the awards that name a spine venue. Eight of 9,672. This is
    a map layer, and it is deliberately tiny; the alternative was a layer built from name
    matches that were 83% wrong.

  federal_operator_profile.json — in-scope spending by operator, fiscal year and agency.
    This is the substantive federal result and it is NOT a map layer. Aramark's federal
    revenue is a fact about Aramark, not about any dot, and drawing it on venues would
    invent a geography the data does not have.

  federal_exclusions.csv — every row that did not make it, with the rule that stopped it.
    9,279 rows. This is the output that makes the other two checkable: without it, "393 of
    9,672" is a number the reader has to take on faith.

    .venv/bin/python -m pipeline.federal.records
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Optional

from .load import RAW, load

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SPINE_IN = OUT / "venues_full.json"

VENUE_AWARDS = "federal_venue_awards.geojson"
OPERATOR_PROFILE = "federal_operator_profile.json"
EXCLUSIONS = "federal_exclusions.csv"

EXCLUSION_COLUMNS = [
    "scope_reason", "award_id", "piid", "operator_raw", "operator_relation",
    "naics_code", "naics_description", "pop_city", "pop_state", "pop_country",
    "fiscal_year", "obligated_amount", "description", "source_file",
]


def _spine() -> dict[str, dict[str, Any]]:
    if not SPINE_IN.exists():
        return {}
    return {v["venue_id"]: v for v in json.loads(SPINE_IN.read_text())}


def venue_feature(rec: dict[str, Any], venue: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": rec["award_id"],
        "geometry": {"type": "Point", "coordinates": [venue["lng"], venue["lat"]]},
        "properties": {
            "award_id": rec["award_id"],
            "piid": rec["piid"],
            "venue_id": rec["venue_id"],
            "venue_name": venue.get("canonical_name"),
            "city": venue.get("city"),
            "state": venue.get("state"),
            "operator": rec["operator_normalized"],
            "operator_raw": rec["operator_raw"],
            "awarding_agency": rec["awarding_agency"],
            "awarding_sub_agency": rec["awarding_sub_agency"],
            # Numeric, so the console's year slider stays an integer comparison — the same
            # reason the tenure layer carries start_year rather than a date string.
            "fiscal_year": int(rec["fiscal_year"]) if rec["fiscal_year"] else None,
            "start_date": rec["start_date"],
            "end_date": rec["end_date"],
            "obligated_amount": rec["obligated_amount"],
            "description": rec["description"],
            "venue_match": rec["venue_match"],
        },
    }


def emit_venue_awards(records: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    spine = _spine()
    features = []
    no_coordinates = 0
    for rec in records:
        if not rec["venue_id"]:
            continue
        venue = spine.get(rec["venue_id"])
        if not venue or venue.get("lat") is None or venue.get("lng") is None:
            no_coordinates += 1
            continue
        features.append(venue_feature(rec, venue))

    (out / VENUE_AWARDS).write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )
    return {"features": len(features), "no_coordinates": no_coordinates}


def operator_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    """In-scope federal spending, grouped the three ways a reader would ask for it.

    Obligations are summed, not counted, and they can be negative: a deobligation returns
    money. Summing is therefore the only honest total — counting awards would make a
    $45,000 catering job and a $32,000,000 dining contract weigh the same.
    """
    kept = [r for r in records if r["in_scope"]]

    # The counts that were dropped are carried out with the ones that survived, because the
    # console states the ratio in prose and had been retyping it. 393 of 9,672 is the whole
    # point of this layer; a number the panel types by hand is a number that keeps reading
    # true after the export moves under it.
    scope_counts: dict[str, int] = {}
    for r in records:
        scope_counts[r["scope_reason"]] = scope_counts.get(r["scope_reason"], 0) + 1

    by_operator: dict[str, dict[str, Any]] = {}
    by_year: dict[int, dict[str, float]] = {}
    by_agency: dict[str, dict[str, Any]] = {}

    for r in kept:
        op = r["operator_normalized"] or "Unresolved"
        amount = r["obligated_amount"] or 0.0
        year = int(r["fiscal_year"]) if r["fiscal_year"] else None

        entry = by_operator.setdefault(op, {"operator": op, "awards": 0, "obligated": 0.0})
        entry["awards"] += 1
        entry["obligated"] += amount

        if year is not None:
            by_year.setdefault(year, {})
            by_year[year][op] = by_year[year].get(op, 0.0) + amount

        agency = r["awarding_sub_agency"] or "Unattributed"
        ag = by_agency.setdefault(agency, {"agency": agency, "awards": 0, "obligated": 0.0})
        ag["awards"] += 1
        ag["obligated"] += amount

    return {
        "awards": len(kept),
        "rows_loaded": len(records),
        "scope_counts": dict(sorted(scope_counts.items(), key=lambda kv: -kv[1])),
        "obligated_total": round(sum(r["obligated_amount"] or 0.0 for r in kept), 2),
        "by_operator": sorted(
            ({**v, "obligated": round(v["obligated"], 2)} for v in by_operator.values()),
            key=lambda e: -e["obligated"],
        ),
        "by_fiscal_year": [
            {"fiscal_year": y, "operators": {k: round(v, 2) for k, v in sorted(ops.items())}}
            for y, ops in sorted(by_year.items())
        ],
        "by_agency": sorted(
            ({**v, "obligated": round(v["obligated"], 2)} for v in by_agency.values()),
            key=lambda e: -e["obligated"],
        ),
    }


def emit_operator_profile(records: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    profile = operator_profile(records)
    (out / OPERATOR_PROFILE).write_text(json.dumps(profile, indent=2))
    return {"operators": len(profile["by_operator"]), "obligated": profile["obligated_total"]}


def emit_exclusions(records: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Every row the scope rule stopped, with the reason, sorted by reason then award.

    Sorted rather than left in read order so a diff between two runs shows what changed
    about the *rules*, not what changed about the order the files were globbed in.
    """
    dropped = [r for r in records if not r["in_scope"]]
    dropped.sort(key=lambda r: (r["scope_reason"], r["award_id"] or ""))

    with (out / EXCLUSIONS).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EXCLUSION_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in dropped:
            w.writerow(r)
    return {"rows": len(dropped)}


def emit(raw: Path = RAW, out: Optional[Path] = None) -> dict[str, Any]:
    out = out or OUT
    out.mkdir(parents=True, exist_ok=True)

    result = load(raw)
    records = result["records"]
    return {
        "stats": result["stats"],
        "problems": result["problems"],
        "venue_awards": emit_venue_awards(records, out),
        "profile": emit_operator_profile(records, out),
        "exclusions": emit_exclusions(records, out),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    r = emit(args.raw, args.out)
    s = r["stats"]

    print(f"\nEMIT federal -> {args.out}")
    print(f"  {VENUE_AWARDS:<32} {r['venue_awards']['features']} features"
          f" ({r['venue_awards']['no_coordinates']} dropped for no coordinates)")
    print(f"  {OPERATOR_PROFILE:<32} {r['profile']['operators']} operators,"
          f" ${r['profile']['obligated']:,.0f} obligated")
    print(f"  {EXCLUSIONS:<32} {r['exclusions']['rows']} rows")
    print(f"\n  {s['in_scope']} of {s['records']} awards in scope;"
          f" {s['venue_matched']} name a spine venue")

    if r["problems"]:
        print(f"\n  SCHEMA PROBLEMS ({len(r['problems'])}):")
        for p in r["problems"][:20]:
            print(f"    {p}")


if __name__ == "__main__":
    main()
