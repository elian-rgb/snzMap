"""Phase 0 gate — is the spine actually a census, or just a big list?

SNZ_PLAN_v2 risks section: "spot-check defunct-venue and alias completeness on a known
sample (e.g., every MLB park 2004-2024) before trusting it as the census."

MLB is the right probe because the 2004-2024 window contains both halves of the problem:
parks that closed inside the window (Shea, Yankee Stadium I, the Metrodome) and parks that
changed sponsor name inside it (Enron -> Minute Maid, Pacific Bell -> AT&T -> Oracle).
A spine that misses either kind will silently drop contract history.

Run: python -m pipeline.spine.spotcheck
"""

from __future__ import annotations

import json
from pathlib import Path

from .build_spine import match_key

OUT = Path(__file__).resolve().parent.parent / "output"

# Every park that hosted an MLB regular-season home game 2004-2024, listed under a name
# used during that window. Compiled by hand — this is the answer key, so it does not come
# from the same source being tested.
MLB_PARKS_2004_2024 = [
    # Still in use at the end of the window
    ("Angel Stadium", "CA"), ("Busch Stadium", "MO"), ("Chase Field", "AZ"),
    ("Citi Field", "NY"), ("Citizens Bank Park", "PA"), ("Comerica Park", "MI"),
    ("Coors Field", "CO"), ("Dodger Stadium", "CA"), ("Fenway Park", "MA"),
    ("Globe Life Field", "TX"), ("Great American Ball Park", "OH"),
    ("Guaranteed Rate Field", "IL"), ("Kauffman Stadium", "MO"),
    ("LoanDepot Park", "FL"), ("Minute Maid Park", "TX"), ("Nationals Park", "DC"),
    ("Oracle Park", "CA"), ("Oriole Park at Camden Yards", "MD"),
    ("PNC Park", "PA"), ("Petco Park", "CA"), ("Progressive Field", "OH"),
    ("Rogers Centre", None), ("T-Mobile Park", "WA"), ("Target Field", "MN"),
    ("Truist Park", "GA"), ("Wrigley Field", "IL"), ("Yankee Stadium", "NY"),
    ("American Family Field", "WI"), ("Tropicana Field", "FL"),
    ("Sutter Health Park", "CA"), ("Steinbrenner Field", "FL"),
    # Closed or replaced inside the window — the real test
    ("Shea Stadium", "NY"), ("Yankee Stadium (1923)", "NY"),
    ("Hubert H. Humphrey Metrodome", "MN"), ("Veterans Stadium", "PA"),
    ("Busch Memorial Stadium", "MO"), ("RFK Stadium", "DC"),
    ("Oakland Coliseum", "CA"), ("Turner Field", "GA"),
    ("Olympic Stadium", None), ("SkyDome", None),
    ("Bank One Ballpark", "AZ"), ("Jacobs Field", "OH"),
    ("Safeco Field", "WA"), ("Miller Park", "WI"), ("Comiskey Park", "IL"),
    ("U.S. Cellular Field", "IL"), ("Pacific Bell Park", "CA"),
    ("SBC Park", "CA"), ("AT&T Park", "CA"), ("Enron Field", "TX"),
    ("Cinergy Field", "OH"), ("Pro Player Stadium", "FL"),
    ("Dolphin Stadium", "FL"), ("Sun Life Stadium", "FL"),
    ("Marlins Park", "FL"), ("Edison International Field of Anaheim", "CA"),
    ("Ameriquest Field in Arlington", "TX"), ("Rangers Ballpark in Arlington", "TX"),
    ("Globe Life Park in Arlington", "TX"), ("The Ballpark in Arlington", "TX"),
    ("Network Associates Coliseum", "CA"), ("McAfee Coliseum", "CA"),
    ("O.co Coliseum", "CA"), ("RingCentral Coliseum", "CA"),
    ("Qualcomm Stadium", "CA"), ("Land Shark Stadium", "FL"),
    ("Citizens Business Bank Arena", "CA"), ("Hiram Bithorn Stadium", None),
    ("Estadio de Béisbol Monterrey", None), ("Fort Bragg Field", "NC"),
    ("TD Ameritrade Park", "NE"), ("Field of Dreams", "IA"),
    ("Rickwood Field", "AL"), ("Williamsport Little League Classic", "PA"),
    ("BB&T Ballpark", "NC"), ("London Stadium", None),
]


def build_index(venues: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for v in venues:
        for key in v["match_keys"]:
            index.setdefault(key, []).append(v)
    return index


def main() -> None:
    venues = json.loads((OUT / "venues_full.json").read_text())
    index = build_index(venues)

    hits, misses, ambiguous = [], [], []
    for name, state in MLB_PARKS_2004_2024:
        probe = name.split(" (")[0]  # "Yankee Stadium (1923)" -> disambiguator is ours
        matches = index.get(match_key(probe), [])
        if not matches:
            misses.append((name, state))
        elif len(matches) > 1:
            ambiguous.append((name, state, [m["venue_id"] for m in matches]))
            hits.append((name, matches[0]))
        else:
            hits.append((name, matches[0]))

    total = len(MLB_PARKS_2004_2024)
    print(f"MLB parks 2004-2024 spot-check — {len(hits)}/{total} matched "
          f"({100 * len(hits) / total:.0f}% recall)\n")

    if misses:
        print(f"MISSING FROM SPINE ({len(misses)}):")
        for name, state in misses:
            print(f"  - {name} ({state or 'non-US'})")
        print()

    if ambiguous:
        print(f"AMBIGUOUS — name matches >1 spine venue ({len(ambiguous)}):")
        for name, state, ids in ambiguous:
            print(f"  - {name} ({state}) -> {ids}")
        print()

    # Alias completeness: a former name should resolve to the venue's current record.
    alias_probes = [
        ("Enron Field", "Daikin Park"),
        ("Pacific Bell Park", "Oracle Park"),
        ("Jacobs Field", "Progressive Field"),
        ("Safeco Field", "T-Mobile Park"),
        ("Miller Park", "American Family Field"),
        ("Bank One Ballpark", "Chase Field"),
        ("Comiskey Park", "Guaranteed Rate Field"),
        ("Turner Field", "Center Parc Stadium"),
    ]
    print("ALIAS RESOLUTION (former name -> current record):")
    alias_ok = 0
    for old, expected_current in alias_probes:
        matches = index.get(match_key(old), [])
        if not matches:
            print(f"  MISS  {old:32s} -> not in spine")
            continue
        current = matches[0]["canonical_name"]
        ok = match_key(current) == match_key(expected_current)
        alias_ok += ok
        print(f"  {'OK  ' if ok else 'DIFF'}  {old:32s} -> {current}"
              f"{'' if ok else f'   (expected {expected_current})'}")
    print(f"\n  {alias_ok}/{len(alias_probes)} former names resolve to the expected venue")

    coverage = {
        "probe": "MLB parks 2004-2024",
        "total": total,
        "matched": len(hits),
        "recall": round(len(hits) / total, 3),
        "missing": [{"name": n, "state": s} for n, s in misses],
        "ambiguous": [{"name": n, "state": s, "venue_ids": i} for n, s, i in ambiguous],
        "alias_probes_passed": alias_ok,
        "alias_probes_total": len(alias_probes),
    }
    (OUT / "spine_spotcheck_mlb.json").write_text(json.dumps(coverage, indent=1))
    print(f"\nWrote {OUT / 'spine_spotcheck_mlb.json'}")


if __name__ == "__main__":
    main()
