"""Gate for the ACS context layer — is every venue reading its own neighbourhood?

The failure this exists to catch is not a crash. ACS context cannot crash the console; it
can only render a plausible number beside the wrong venue, in the wrong decade's boundaries,
or in dollars that are not comparable to the dollars next to them. Every check below is
aimed at one of those three.

Same two halves as the federal gate. The RULE CHECKS run `validate_acs` against hand-written
rows that should trip each rule and rows that should not; they prove the rules exist. The
INVARIANTS run over the real 100k-row join and prove the rules were applied — and they
assert the export is present and non-trivial, so they cannot pass on empty data.

Two invariants are worth calling out because they check something outside this module. The
subject tables S0801 and S1903 were downloaded but are not read; instead the gate asserts
they agree with the detailed tables they duplicate. That converts unused data into a test of
the data that *is* used — if a future re-download misaligns a column, the disagreement
surfaces here rather than as a slightly wrong percentage on a venue panel.

    .venv/bin/python -m pipeline.acs.check_rules
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..schema import ACS_LAST_2010_VINTAGE, validate_acs
from .load import DOWNLOADS, _GEOID_RE, _num, build

ROOT = Path(__file__).resolve().parent.parent


def row(**over: Any) -> dict[str, Any]:
    """A well-formed 2015 context row, so a test can break exactly one thing."""
    r = {
        "venue_id": "wd-Q1",
        "year": 2015,
        "zcta": "20001",
        "zcta_vintage": 2010,
        "zcta_match": "both_vintages",
        "workers_total": 1000.0,
        "median_household_income": 65000.0,
        "transit_share": 0.35,
        "long_commute_share": 0.12,
        "source_file": "ACS5Y2015 B08006/B08303/B19013 (ZCTA)",
    }
    r.update(over)
    return r


# (label, row, should it validate cleanly)
RULE_CHECKS: list[tuple[str, dict[str, Any], bool]] = [
    ("a well-formed row validates", row(), True),
    ("a 2015 row on 2020 ZCTAs is rejected", row(zcta_vintage=2020), False),
    ("a 2024 row on 2010 ZCTAs is rejected", row(year=2024, zcta_vintage=2010), False),
    ("a 2024 row on 2020 ZCTAs is fine",
     row(year=2024, zcta_vintage=2020, zcta_match="both_vintages"), True),
    (f"{ACS_LAST_2010_VINTAGE} is still the last 2010-ZCTA vintage",
     row(year=ACS_LAST_2010_VINTAGE, zcta_vintage=2010), True),
    (f"{ACS_LAST_2010_VINTAGE + 1} has already switched",
     row(year=ACS_LAST_2010_VINTAGE + 1, zcta_vintage=2020), True),
    ("no_zcta carrying a zcta is rejected", row(zcta_match="no_zcta"), False),
    ("2020_only quoting a 2010 ZCTA is rejected",
     row(zcta_match="2020_only", zcta_vintage=2010), False),
    ("2010_only quoting a 2020 ZCTA is rejected",
     row(year=2024, zcta_match="2010_only", zcta_vintage=2020), False),
    ("measures without a ZCTA are rejected",
     row(zcta=None, zcta_vintage=None, zcta_match="no_zcta"), False),
    ("an empty row with no ZCTA is fine",
     row(zcta=None, zcta_vintage=None, zcta_match="no_zcta", workers_total=None,
         median_household_income=None, transit_share=None, long_commute_share=None), True),
    ("a share above 1 is rejected", row(transit_share=1.4), False),
    ("a negative share is rejected", row(long_commute_share=-0.1), False),
    ("a share with no workers behind it is rejected",
     row(workers_total=0, transit_share=0.2), False),
    ("negative workers are rejected", row(workers_total=-5), False),
    ("an unknown match reason is rejected", row(zcta_match="probably"), False),
]

INVARIANTS: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []


def invariant(label: str) -> Callable[[Callable[[dict[str, Any]], bool]], Any]:
    def register(fn: Callable[[dict[str, Any]], bool]) -> Callable[[dict[str, Any]], bool]:
        INVARIANTS.append((label, fn))
        return fn
    return register


@invariant("the join is actually there and non-trivial")
def _loaded(r: dict[str, Any]) -> bool:
    return len(r["records"]) > 50000


@invariant("every row validates against ACS_FIELDS")
def _valid(r: dict[str, Any]) -> bool:
    return not r["problems"]


@invariant("every venue in the spine gets a row in every vintage, with none left over")
def _accounting(r: dict[str, Any]) -> bool:
    return len(r["records"]) == len(r["venues"]) * len(r["years"])


@invariant("(venue_id, year) is unique, so no venue is counted twice in a year")
def _unique(r: dict[str, Any]) -> bool:
    keys = [(x["venue_id"], x["year"]) for x in r["records"]]
    return len(keys) == len(set(keys))


@invariant("the whole 2011-2024 series is present")
def _series(r: dict[str, Any]) -> bool:
    return r["years"] == list(range(2011, 2025))


@invariant("every row's ZCTA vintage is the one its year was published on")
def _vintage(r: dict[str, Any]) -> bool:
    return all(
        x["zcta_vintage"] == (2010 if x["year"] <= ACS_LAST_2010_VINTAGE else 2020)
        for x in r["records"]
        if x["zcta_vintage"] is not None
    )


@invariant("the two ZCTA eras really are different geographies, not a redundant lookup")
def _eras_differ(r: dict[str, Any]) -> bool:
    # If this ever passes trivially — every venue in the same ZCTA both eras — the two-vintage
    # machinery is dead weight and the claim in the docstring is false. Measured, not assumed.
    pairs = {
        (x["venue_id"], x["zcta_vintage"]): x["zcta"]
        for x in r["records"]
        if x["zcta"]
    }
    venues = {v for v, _ in pairs}
    changed = sum(
        1
        for v in venues
        if pairs.get((v, 2010)) and pairs.get((v, 2020))
        and pairs[(v, 2010)] != pairs[(v, 2020)]
    )
    return changed > 0


@invariant("no venue reports a measure without a ZCTA to have measured")
def _no_orphan_measures(r: dict[str, Any]) -> bool:
    return not any(
        x["zcta"] is None
        and (x["workers_total"] is not None or x["median_household_income"] is not None)
        for x in r["records"]
    )


@invariant("every share is a share of something, and lies in 0-1")
def _shares(r: dict[str, Any]) -> bool:
    for x in r["records"]:
        for share in ("transit_share", "long_commute_share"):
            v = x[share]
            if v is not None and not (0.0 <= v <= 1.0):
                return False
    return True


@invariant("every non-numeric income cell is handled the way its own meaning requires")
def _suppression(r: dict[str, Any]) -> bool:
    """Re-reads the raw file and checks `_num` against it, cell by cell.

    Written this way because the obvious version — "no income is negative" — cannot fail on
    this data: these downloads encode suppression as "-", not as the -666666666 sentinel, so
    a check for negative numbers passes no matter how badly the parser is broken. Sabotaging
    `_num` to let sentinels through was not detected by it, which is how this got rewritten.

    The three cases have three different right answers, and conflating any two is the bug:
      "-"        suppressed, too few households  -> None
      "250,000+" top-coded, median is >= 250000  -> 250000
      "2,500-"   bottom-coded, median <= 2500    -> 2500
    """
    from .load import _BOUNDS, read_table, _tables

    year = 2024
    loaded = read_table("B19013", ["B19013_001E"], _tables()["B19013"][2])[year]
    path = DOWNLOADS / "Median Household Income in the Past 12 Months" / (
        f"ACSDT5Y{year}.B19013-Data.csv"
    )
    checked = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        next(reader)
        for raw in reader:
            geo = _GEOID_RE.search(raw["GEO_ID"] or "")
            if not geo or geo.group(1) not in loaded:
                continue
            cell = (raw["B19013_001E"] or "").strip()
            got = loaded[geo.group(1)]["B19013_001E"]
            if cell in _BOUNDS:
                checked += 1
                if got != _BOUNDS[cell]:
                    return False
            elif cell == "-":
                checked += 1
                if got is not None:
                    return False
            elif got is None:
                return False  # a plain number that failed to parse
    # If the file ever stops containing coded cells this check has gone quiet, and a check
    # that cannot fail is not a check.
    return checked > 100


@invariant("most venues actually got context — a join that matches nothing is not a join")
def _coverage(r: dict[str, Any]) -> bool:
    joined = {x["venue_id"] for x in r["records"] if x["zcta"]}
    return len(joined) > 0.9 * len(r["venues"])


def _subject_column(table: str, folder: str, year: int, column: str) -> dict[str, Optional[float]]:
    """One column of a subject table, keyed by ZCTA, for the cross-check invariants."""
    path = DOWNLOADS / folder / f"ACSST5Y{year}.{table}-Data.csv"
    values: dict[str, Optional[float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if column not in (reader.fieldnames or []):
            raise KeyError(f"{path.name}: no column {column}")
        next(reader)
        for r in reader:
            geo = _GEOID_RE.search(r["GEO_ID"] or "")
            if geo:
                values[geo.group(1)] = _num(r[column])
    return values


@invariant("S0801's worker count agrees with B08006's, so reading one of them is enough")
def _s0801_agrees(r: dict[str, Any]) -> bool:
    from .load import read_table, _tables

    year = 2024
    detailed = read_table("B08006", ["B08006_001E"], _tables()["B08006"][2])[year]
    subject = _subject_column(
        "S0801", "Commuting Characteristics by Sex", year, "S0801_C01_001E"
    )
    shared = set(detailed) & set(subject)
    if len(shared) < 30000:
        return False
    return all(detailed[z]["B08006_001E"] == subject[z] for z in shared)


@invariant("S1903's median household income agrees with B19013's")
def _s1903_agrees(r: dict[str, Any]) -> bool:
    from .load import read_table, _tables

    year = 2024
    detailed = read_table("B19013", ["B19013_001E"], _tables()["B19013"][2])[year]
    subject = _subject_column(
        "S1903", "Median Income in the Past 12 Months", year, "S1903_C03_001E"
    )
    shared = set(detailed) & set(subject)
    if len(shared) < 30000:
        return False
    return all(detailed[z]["B19013_001E"] == subject[z] for z in shared)


def main() -> int:
    rule_failures: list[str] = []
    invariant_failures: list[str] = []

    for label, r, should_pass in RULE_CHECKS:
        problems = validate_acs(r)
        if should_pass and problems:
            rule_failures.append(f"{label}\n      expected clean, got {problems}")
        elif not should_pass and not problems:
            rule_failures.append(f"{label}\n      expected a complaint, got none")

    records = build()
    result = {
        "records": records,
        "problems": [p for x in records for p in validate_acs(x)],
        "venues": {x["venue_id"] for x in records},
        "years": sorted({x["year"] for x in records}),
    }

    for label, check in INVARIANTS:
        try:
            ok = check(result)
        except Exception as exc:                                    # noqa: BLE001
            invariant_failures.append(f"{label}: raised {exc!r}")
            continue
        if not ok:
            invariant_failures.append(label)

    joined = {x["venue_id"] for x in records if x["zcta"]}
    print(f"acs rules  : {len(RULE_CHECKS) - len(rule_failures)}/{len(RULE_CHECKS)} pass")
    print(f"invariants : {len(INVARIANTS) - len(invariant_failures)}/{len(INVARIANTS)} pass")
    print(f"rows       : {len(records):,}  ({len(result['venues']):,} venues x "
          f"{len(result['years'])} vintages, {len(joined):,} venues joined)")

    for f in rule_failures + invariant_failures:
        print(f"  FAIL  {f}")

    if rule_failures or invariant_failures:
        return 1
    print(f"\nPASS — {len(RULE_CHECKS) + len(INVARIANTS)} checks over "
          f"{len(records):,} real venue-year rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
