"""Emit the ACS context the console reads, plus a flat CSV for auditing.

Two outputs, and the split is deliberate:

  acs_venue_context.json  keyed venue -> year, for the console. Rounded, compact.
  acs_venue_context.csv   one row per venue-year, unrounded, for checking by hand.

The JSON is the only thing shipped to the browser, so everything a reader needs to *not*
be misled by it travels with it: which ZCTA vintage each half of the series used, how many
venues could not be joined at all, and the fact that median income is nominal.

    .venv/bin/python -m pipeline.acs.records
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..schema import ACS_FIELDS, ACS_LAST_2010_VINTAGE
from .load import build

OUT = Path(__file__).resolve().parent.parent / "output"

JSON_PATH = OUT / "acs_venue_context.json"
CSV_PATH = OUT / "acs_venue_context.csv"

# Shares are ratios of survey estimates with margins of error in the thousands. Four
# decimals is already more precision than the data supports; it is kept only so the console
# can render a whole-number percentage without a second rounding changing the last digit.
SHARE_DP = 4

# Each year is stored as a positional array in this order rather than as an object with
# four named keys. Named keys cost about 60 bytes per venue-year, which across 96,376 rows
# is 12.7 MB of repeated field names shipped to the browser next to a 4.2 MB spine. The
# names live here once instead, and travel with the file so the array is self-describing.
SERIES_COLUMNS = [
    "workers_total",
    "median_household_income",
    "transit_share",
    "long_commute_share",
]

INCOME_NOTE = (
    "Median household income is published in the dollars of each vintage year "
    "(the 2011 figure is 2011 dollars, the 2024 figure is 2024 dollars). Nothing here "
    "deflates it, so the series is not a real-terms trend. ACS also censors the extremes: "
    "a ZCTA median at or above $250,000 is published as a bound, not an estimate, and so "
    "is one at or below $2,500. Both are carried at their bound rather than dropped."
)

GEOGRAPHY_NOTE = (
    f"ACS 5-year vintages through {ACS_LAST_2010_VINTAGE} are tabulated on 2010-Census "
    "ZCTAs and later vintages on 2020-Census ZCTAs. Each venue was located in both, so "
    "each half of the series uses the boundaries that half was published on."
)

SCOPE_NOTE = (
    "A ZCTA is a postal-delivery area, not the venue. It describes the neighbourhood the "
    "venue sits in — offices, housing and all — and is context for reading a venue, never "
    "evidence about the venue itself."
)


def _round(v: Any) -> Any:
    return None if v is None else round(v, SHARE_DP)


def emit() -> dict[str, Any]:
    records = build()

    years = sorted({r["year"] for r in records})
    venues: dict[str, dict[str, Any]] = {}
    for r in records:
        entry = venues.setdefault(
            r["venue_id"],
            {
                "zcta_match": r["zcta_match"],
                "zcta_2010": None,
                "zcta_2020": None,
                "years": {},
            },
        )
        if r["zcta"]:
            entry[f"zcta_{r['zcta_vintage']}"] = r["zcta"]
        # Years with nothing to say are left out rather than stored as four nulls. The
        # console reads a missing year as "no data", which is the same statement.
        if r["workers_total"] is None and r["median_household_income"] is None:
            continue
        entry["years"][str(r["year"])] = [
            None if r["workers_total"] is None else int(r["workers_total"]),
            None if r["median_household_income"] is None else int(r["median_household_income"]),
            _round(r["transit_share"]),
            _round(r["long_commute_share"]),
        ]

    joined = sum(1 for v in venues.values() if v["years"])
    coverage: dict[str, int] = {}
    for v in venues.values():
        coverage[v["zcta_match"]] = coverage.get(v["zcta_match"], 0) + 1

    payload = {
        "years": years,
        "series_columns": SERIES_COLUMNS,
        "venues_total": len(venues),
        "venues_with_context": joined,
        "coverage_by_match": coverage,
        "geography_note": GEOGRAPHY_NOTE,
        "income_note": INCOME_NOTE,
        "scope_note": SCOPE_NOTE,
        "venues": venues,
    }
    JSON_PATH.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    columns = [f[0] for f in ACS_FIELDS]
    with CSV_PATH.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        # Sorted so a diff between runs shows a rule change rather than dict ordering.
        for r in sorted(records, key=lambda r: (r["venue_id"], r["year"])):
            writer.writerow({c: r.get(c) for c in columns})

    return payload


def main() -> None:
    payload = emit()
    print(f"{JSON_PATH.name}: {JSON_PATH.stat().st_size / 1e6:.1f} MB")
    print(f"{CSV_PATH.name}: {sum(1 for _ in CSV_PATH.open()) - 1:,} rows")
    print(
        f"{payload['venues_with_context']:,} of {payload['venues_total']:,} venues have "
        f"context in at least one of {len(payload['years'])} vintages"
    )
    for reason, n in sorted(payload["coverage_by_match"].items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<16} {n:,}")


if __name__ == "__main__":
    main()
