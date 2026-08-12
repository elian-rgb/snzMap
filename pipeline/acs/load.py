"""Read the ACS ZCTA exports and attach neighbourhood context to each venue.

Five tables were downloaded, and only three are read:

  B08006  Sex of Workers by Means of Transportation to Work  -> workers, transit share
  B08303  Travel Time to Work                                -> long-commute share
  B19013  Median Household Income                            -> income

  S0801   Commuting Characteristics by Sex     — not read
  S1903   Median Income in the Past 12 Months  — not read

The two subject tables are pre-tabulated views of the same universes as the three detailed
tables: S0801_C01_001E is the same "workers 16 years and over" count as B08006_001E, and
S1903_C03_001E is the same median household income as B19013_001E. Reading both would give
two columns that must agree and no way to notice when they do not — so `check_rules` asserts
the agreement instead, which turns the redundancy into a test rather than duplicate data.

The vintage split is the thing to be careful about. The exports change tabulation geography
between the 2020 and 2021 five-year releases, so a venue's ZCTA for 2011-2020 and its ZCTA
for 2021-2024 are answers to different questions. `pipeline.acs.geocode` resolves both and
this module picks per year; it never carries one across the break.

    .venv/bin/python -m pipeline.acs.load
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from ..schema import ACS_LAST_2010_VINTAGE, validate_acs

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
DOWNLOADS = Path.home() / "Downloads"

VENUES = OUT / "venues_full.json"
ZCTA_CACHE = OUT / "venue_zcta.json"

# folder name -> (table id, columns needed). The folder names are the titles data.census.gov
# gives the download, kept verbatim so the mapping to what the user actually clicked is
# obvious. A renamed folder fails loudly in `_tables` rather than yielding an empty series.
TABLES = {
    "Sex of Workers by Means of Transportation to Work": (
        "B08006",
        ["B08006_001E", "B08006_008E"],
    ),
    "Travel Time to Work": (
        "B08303",
        ["B08303_001E", "B08303_011E", "B08303_012E", "B08303_013E"],
    ),
    "Median Household Income in the Past 12 Months": ("B19013", ["B19013_001E"]),
}

# ACSDT5Y2024.B19013-Data.csv -> 2024
_VINTAGE_RE = re.compile(r"ACS[A-Z]{2}5Y(\d{4})\.")

# data.census.gov writes GEO_ID as 860Z200US00601 (2020) or 8600000US00601 (2010); the ZCTA
# is always the tail after "US".
_GEOID_RE = re.compile(r"US(\d{5})$")


# Median income cells that are bounds rather than estimates. These are NOT suppression:
# ACS top-codes any ZCTA median at or above $250,000 and bottom-codes at or below $2,500,
# so the value is known, just censored. In the 2024 file 118 ZCTAs are top-coded and 15 are
# bottom-coded. Treating them as unparseable — which is what a bare float() does — would
# drop them to null and quietly delete the richest neighbourhoods from every average,
# because the censoring is not random. They are parsed to their bound instead, and
# `records.py` says so in the note that ships with the data.
_BOUNDS = {"250,000+": 250000.0, "2,500-": 2500.0}


def _num(v: str) -> Optional[float]:
    """ACS suppression codes are not numbers and must not become zeros.

    A suppressed median income (printed as "-") means "too few households to publish",
    which is a different fact from "$0" and would drag any average that swallowed it. It
    becomes None so it stays visibly absent.
    """
    v = (v or "").strip()
    if not v:
        return None
    if v in _BOUNDS:
        return _BOUNDS[v]
    try:
        n = float(v)
    except ValueError:
        return None
    # Older vintages of the API-shaped data use large negative sentinels for suppression.
    return None if n <= -100000000 else n


def _tables() -> dict[str, tuple[str, list[str], Path]]:
    found = {}
    for folder, (table, columns) in TABLES.items():
        path = DOWNLOADS / folder
        if not path.is_dir():
            raise FileNotFoundError(f"ACS export folder missing: {path}")
        found[table] = (table, columns, path)
    return found


def read_table(table: str, columns: list[str], folder: Path) -> dict[int, dict[str, dict]]:
    """{vintage_year: {zcta: {column: value}}} for one ACS table."""
    by_year: dict[int, dict[str, dict]] = {}
    for path in sorted(folder.glob(f"*.{table}-Data.csv")):
        m = _VINTAGE_RE.search(path.name)
        if not m:
            raise ValueError(f"cannot read a vintage year from {path.name}")
        year = int(m.group(1))

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in columns if c not in (reader.fieldnames or [])]
            if missing:
                raise KeyError(f"{path.name}: missing columns {missing}")
            next(reader)  # the second row is the human-readable header, not data

            rows: dict[str, dict] = {}
            for row in reader:
                geo = _GEOID_RE.search(row["GEO_ID"] or "")
                if not geo:
                    continue
                rows[geo.group(1)] = {c: _num(row[c]) for c in columns}
        by_year[year] = rows
    if not by_year:
        raise FileNotFoundError(f"no {table} data files under {folder}")
    return by_year


def _share(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """None rather than 0 when there is nothing to divide by.

    Plenty of ZCTAs are industrial or institutional and report zero workers. A 0.0 there
    would render as "0% take transit", which reads as a finding; None renders as no data,
    which is what it is.
    """
    if not denominator or numerator is None:
        return None
    return numerator / denominator


def build() -> list[dict[str, Any]]:
    venues = json.loads(VENUES.read_text())
    if not ZCTA_CACHE.exists():
        raise FileNotFoundError(
            f"{ZCTA_CACHE.name} not found — run pipeline.acs.geocode first"
        )
    zctas = json.loads(ZCTA_CACHE.read_text())

    data = {t: read_table(t, cols, folder) for t, (_, cols, folder) in _tables().items()}
    years = sorted(set.intersection(*(set(d) for d in data.values())))

    records: list[dict[str, Any]] = []
    for venue in venues:
        # The 6,884 venues that carry a coordinate — exactly the set in venues.geojson, and
        # so exactly the dots on the map. `in_scope` in venues_full.json is a narrower flag
        # about the tenure hunt, not about being mapped, and keying on it would leave 2,904
        # visible dots with no context and no record saying why.
        if not (venue.get("lat") and venue.get("lng")):
            continue

        assignment = zctas.get(venue["venue_id"])
        if assignment is None:
            assignment = {"zcta_2010": None, "zcta_2020": None, "zcta_match": "no_zcta"}

        for year in years:
            vintage = 2010 if year <= ACS_LAST_2010_VINTAGE else 2020
            zcta = assignment[f"zcta_{vintage}"]

            b08006 = data["B08006"][year].get(zcta) if zcta else None
            b08303 = data["B08303"][year].get(zcta) if zcta else None
            b19013 = data["B19013"][year].get(zcta) if zcta else None

            workers = b08006["B08006_001E"] if b08006 else None
            commuters = b08303["B08303_001E"] if b08303 else None
            long_commute = (
                sum(
                    v
                    for c in ("B08303_011E", "B08303_012E", "B08303_013E")
                    if (v := b08303[c]) is not None
                )
                if b08303
                else None
            )

            records.append(
                {
                    "venue_id": venue["venue_id"],
                    "year": year,
                    # Blank rather than the code the geocoder returned when this vintage's
                    # ACS has no such ZCTA: a code with no data behind it is worse than a
                    # blank, because it looks like a successful join.
                    "zcta": zcta if b08006 or b19013 else None,
                    "zcta_vintage": vintage if (b08006 or b19013) else None,
                    "zcta_match": assignment["zcta_match"],
                    "workers_total": workers,
                    "median_household_income": b19013["B19013_001E"] if b19013 else None,
                    "transit_share": _share(
                        b08006["B08006_008E"] if b08006 else None, workers
                    ),
                    "long_commute_share": _share(long_commute, commuters),
                    "source_file": f"ACS5Y{year} B08006/B08303/B19013 (ZCTA)",
                }
            )
    return records


def main() -> None:
    records = build()
    problems = [p for r in records for p in validate_acs(r)]

    years = sorted({r["year"] for r in records})
    venues = {r["venue_id"] for r in records}
    joined = {r["venue_id"] for r in records if r["zcta"]}
    matches: dict[str, set] = {}
    for r in records:
        matches.setdefault(r["zcta_match"], set()).add(r["venue_id"])

    print(f"{len(records):,} rows — {len(venues):,} venues x {len(years)} vintages "
          f"({years[0]}-{years[-1]})")
    print(f"{len(joined):,} venues have ACS context in at least one year")
    for reason, ids in sorted(matches.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason:<16} {len(ids):,}")
    print(f"schema problems: {len(problems)}")
    for p in problems[:10]:
        print(f"  {p}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
