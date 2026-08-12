"""Venue coordinates -> ZIP Code Tabulation Area, in both ZCTA vintages.

Why two vintages rather than one. The ACS exports on disk switch tabulation geography
between the 2020 and 2021 five-year releases: every file through ACSDT5Y2020 has 33,120
ZCTA rows and every file from ACSDT5Y2021 has 33,774. The 2020-Census ZCTAs are not a
refinement of the 2010 ones — codes are added, dropped, and in places redrawn while keeping
the same five digits. A venue joined once and applied to all fourteen vintages would
therefore be joined correctly for one half of the series and silently, unfalsifiably wrong
for the other. So each venue gets a 2010 ZCTA and a 2020 ZCTA, and `load.py` picks by year.

Why the Census geocoder rather than a local point-in-polygon. The alternative is the TIGER
ZCTA boundary file (~500 MB, or ~60 MB for the generalized version) plus a shapefile reader
plus a ray-casting routine — three new dependencies and a large binary in the repo to answer
a question the Census answers authoritatively for free. The geocoder is also still keyless,
which the ACS data API is not: as of 2026-08 an unkeyed `api.census.gov` request redirects
to `missing_key.html`.

Why not `common.http.PoliteSession`. That client enforces a one-second floor between
requests, which is right for Overpass and WDQS — expensive analytic queries against a shared
research endpoint. This is a public point lookup, 7.5k venues x 2 vintages, and a
one-second floor would make the run four hours. It uses a small thread pool instead, and
pays for that by being resumable: results are flushed to disk as they arrive, so a dropped
connection costs the remaining venues rather than the whole run.
"""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests

from ..common.http import USER_AGENT

OUTPUT = Path(__file__).resolve().parent.parent / "output"
VENUES = OUTPUT / "venues_full.json"
CACHE = OUTPUT / "venue_zcta.json"

GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
LAYER = "ZIP Code Tabulation Areas"

# The geocoder does not spell the layer the same way in both vintages: the 2010 response
# keys it "ZIP Code Tabulation Areas" and the 2020 response keys it "Zip Code Tabulation
# Areas". Matching the key literally made every 2020 lookup return an empty list, which is
# indistinguishable from "this point is not in any ZCTA" — so the first run reported all 19
# test venues as 2010_only and nothing raised. The key is matched case-insensitively now,
# and a response carrying some other layer instead is an error rather than an empty answer.
def _areas(geographies: dict) -> list:
    # An entirely empty `geographies` is the geocoder's real answer for a point no ZCTA
    # covers — ZCTAs are built from addressed mail delivery, so unaddressed land has none.
    # A venue in remote Modoc County, California returns this. It is data, not an error.
    if not geographies:
        return []
    for key, value in geographies.items():
        if key.lower() == LAYER.lower():
            return value or []
    raise KeyError(f"no ZCTA layer in geocoder response; got {sorted(geographies)}")

# Keyed by the name used in the emitted record, valued by the geocoder's vintage id.
VINTAGES = {"zcta_2010": "Census2010_Current", "zcta_2020": "Census2020_Current"}

WORKERS = 8
TIMEOUT_S = 30
ATTEMPTS = 3


def _lookup(session: requests.Session, lng: float, lat: float, vintage: str) -> Optional[str]:
    """One point, one vintage. `None` means the point is outside every ZCTA.

    That is a real answer, not a failure: ZCTAs cover addressable land, so a venue whose
    spine coordinate landed on a pier, a reservoir or a stretch of coastline genuinely has
    no ZCTA. Returning None here is what lets the caller record `no_zcta` as a judgement
    instead of dropping the venue.
    """
    params = {
        "x": lng,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": vintage,
        "layers": LAYER,
        "format": "json",
    }
    last: Optional[Exception] = None
    for _ in range(ATTEMPTS):
        try:
            resp = session.get(GEOCODER, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            areas = _areas(resp.json()["result"]["geographies"])
            return areas[0]["ZCTA5"] if areas else None
        except Exception as exc:  # noqa: BLE001 - network and shape errors are both retryable
            last = exc
    raise RuntimeError(f"geocoder failed for ({lng}, {lat}) {vintage}: {last}")


def _match_reason(zctas: dict) -> str:
    """How much of the fourteen-year series this venue can actually be given context for."""
    has_2010 = zctas["zcta_2010"] is not None
    has_2020 = zctas["zcta_2020"] is not None
    if has_2010 and has_2020:
        return "both_vintages"
    if has_2020:
        return "2020_only"
    if has_2010:
        return "2010_only"
    return "no_zcta"


def run(limit: Optional[int] = None) -> dict:
    venues = json.loads(VENUES.read_text())
    if limit:
        venues = venues[:limit]

    done = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [v for v in venues if v["venue_id"] not in done and v.get("lat") and v.get("lng")]
    print(f"{len(venues)} venues, {len(done)} already resolved, {len(todo)} to fetch")

    lock = threading.Lock()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    def resolve(venue: dict) -> None:
        zctas = {
            name: _lookup(session, venue["lng"], venue["lat"], vintage)
            for name, vintage in VINTAGES.items()
        }
        record = {**zctas, "zcta_match": _match_reason(zctas)}
        with lock:
            done[venue["venue_id"]] = record
            # Flushed on a cadence rather than per venue: 7.5k rewrites of a 7.5k-entry
            # file is quadratic, and losing at most 200 lookups to a crash is cheap.
            if len(done) % 200 == 0:
                CACHE.write_text(json.dumps(done, indent=1, sort_keys=True))
                print(f"  {len(done)} resolved", flush=True)

    try:
        if todo:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(resolve, todo))
    finally:
        # Written even when a lookup raises. The run is resumable only if the work it did
        # before failing survives; without this a crash at venue 7,000 costs all 7,000.
        CACHE.write_text(json.dumps(done, indent=1, sort_keys=True))

    counts: dict = {}
    for rec in done.values():
        counts[rec["zcta_match"]] = counts.get(rec["zcta_match"], 0) + 1
    return counts


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    counts = run(limit)
    print(f"\nwrote {CACHE.relative_to(OUTPUT.parent.parent)}")
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<16} {n}")


if __name__ == "__main__":
    main()
