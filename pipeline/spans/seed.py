"""Build a paste-ready seeding template for the gold set.

The gold rows themselves have to come from Kiki — an eval set written by the author of the
thing being evaluated grades nothing. But the *tedious* half of a gold row is not
judgment, it is transcription: exact venue spelling, city, state, coordinates to four
decimals. That half is already in the spine.

So this takes a list of venue names as she'd say them and emits the workbook's 16 columns
with the venue identity filled in and the contract facts left blank. She types what she
knows; the spine supplies what it already knows.

Deliberately blank in the output:
  * `operator`, `start_date`, `end_date` — the actual knowledge being captured.
  * `end_status` — pre-filling this would be the exact mistake the plan warns about.
    `ongoing` is an assertion and `unknown` is an admission; a default would silently turn
    one into the other. It stays empty until a human picks.

Names may carry hints after a pipe when the bare name is ambiguous — and it often is,
since the three Madison Square Gardens are all in Manhattan:

    "Madison Square Garden | 2005"          disambiguate by year
    "Wrigley Field | Chicago, IL"           disambiguate by place
    "Busch Stadium | St. Louis, MO | 2010"  both

    .venv/bin/python -m pipeline.spans.seed "Coors Field" "Madison Square Garden | 2005"
    .venv/bin/python -m pipeline.spans.seed --file my_venues.txt
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from ..schema import SPINE_TO_TENURE_TYPE, WORKBOOK_TENURE_COLUMNS
from .gold import _load_spine_index, resolve_venue

OUT = Path(__file__).resolve().parent.parent / "output"
SEED_CSV = OUT / "gold_seed.csv"


def parse_entry(entry: str) -> tuple[dict[str, Any], int | None]:
    """'Busch Stadium | St. Louis, MO | 2010' -> ({name, city, state}, 2010)."""
    parts = [p.strip() for p in entry.split("|")]
    row: dict[str, Any] = {"venue_name": parts[0]}
    year = None
    for hint in parts[1:]:
        if re.fullmatch(r"\d{4}", hint):
            year = int(hint)
        elif "," in hint:
            city, state = hint.rsplit(",", 1)
            row["city"], row["state"] = city.strip(), state.strip().upper()
        else:
            row["state" if len(hint) == 2 else "city"] = hint.upper() if len(hint) == 2 else hint
    return row, year


def _describe(c: dict[str, Any]) -> str:
    """Candidate line for an ambiguous name — dates included, since they are usually what
    tells the three Madison Square Gardens apart."""
    where = f"{c['canonical_name']} ({c['city']}, {c['state']}"
    opened, closed = str(c.get("opened_date") or "")[:4], str(c.get("closed_date") or "")[:4]
    if opened or closed:
        where += f", {opened or '?'}-{closed or 'open'}"
    return where + ")"


def build(entries: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    index = _load_spine_index()
    rows, unresolved = [], []

    for entry in entries:
        query, year = parse_entry(entry)
        name = query["venue_name"]
        res = resolve_venue(query, index, year=year)
        if not res["venue_id"]:
            if res["match"] == "ambiguous":
                where = "; ".join(_describe(c) for c in res["candidates"])
                unresolved.append(f"{name}: ambiguous — add '| City, ST' or '| YEAR'. {where}")
            else:
                unresolved.append(f"{name}: {res['match']} — not in the spine, so it needs a spine record first")
            continue

        row = {c: "" for c in WORKBOOK_TENURE_COLUMNS}
        row["venue_name"] = res["matched_name"]
        row["venue_type"] = SPINE_TO_TENURE_TYPE.get(res["spine_type"] or "", "other")
        row["city"] = res["spine_city"] or ""
        row["state"] = res["spine_state"] or ""
        row["lat"] = res["spine_lat"] if res["spine_lat"] is not None else ""
        row["lng"] = res["spine_lng"] if res["spine_lng"] is not None else ""
        # Not a workbook column, so it cannot go in the sheet — printed below instead.
        rows.append({**row, "_venue_id": res["venue_id"], "_asked_for": name, "_match": res["match"]})

    return rows, unresolved


def main(argv: list[str]) -> int:
    if "--file" in argv:
        path = Path(argv[argv.index("--file") + 1])
        names = [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        names = [a for a in argv if not a.startswith("--")]

    if not names:
        print(__doc__)
        return 1

    rows, unresolved = build(names)

    OUT.mkdir(exist_ok=True)
    with SEED_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=WORKBOOK_TENURE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)}/{len(names)} resolved -> {SEED_CSV}")
    print("  paste under the header on the tenure_table tab, then fill operator + dates + end_status\n")
    for r in rows:
        note = "" if r["_match"] == "exact" else f"  (matched '{r['_asked_for']}' via alias)"
        print(f"  {r['venue_name']:38} {r['city']}, {r['state']:2}  {r['_venue_id']}{note}")
    for u in unresolved:
        print(f"  UNRESOLVED {u}")

    (OUT / "gold_seed_venue_ids.json").write_text(
        json.dumps({r["venue_name"]: r["_venue_id"] for r in rows}, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
