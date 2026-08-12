"""Venue coordinates -> the municipality the venue is actually in.

The spine's `city` came from Wikidata P131 "located in the administrative territorial
entity", read one level deep and unfiltered. P131 is a chain — a venue points at a village,
which points at a town, which points at a county, which points at a state — and which rung
a given item happens to sit on is an editorial accident of whoever wrote that item. So
`?venue wdt:P131 ?city` returns a municipality for some venues and a state for others, and
nothing downstream could tell the two apart. 2,480 of the 6,884 mapped venues (36.0%) ended
up holding their own state's name in `city`: the US Coast Guard Academy's city was
"Connecticut".

That is worse than a blank. A blank is a gap a reader can see; "Connecticut" is a wrong
answer wearing the costume of a right one, and it silently broke every join and filter that
touched it. The federal award join lost real matches to it, and the console's place filter
had to be built on `state` instead of city because city could not be trusted.

The fix does not go back to Wikidata. Constraining the SPARQL to municipality-typed items
means enumerating what counts as a municipality across fifty states — city, town, village,
borough, township, consolidated city-county, independent city, CDP — and the answer would
still be only as good as each item's P31. The venue's coordinate is better evidence than its
metadata, and the Census answers "what municipality is this point in" authoritatively, for
free, without a key, from the same endpoint the ZCTA join already uses.

Two layers are read, in order:

  Incorporated Places       legal municipalities. 41 of a 60-venue sample.
  Census Designated Places  the Census's name for a populated place that is not incorporated
                            — "Pepperdine University CDP". 4 more of the sample.

County Subdivisions is deliberately NOT used as a third fallback even though it answers for
almost every remaining point, because what it answers is not a city name. On the same sample
it returned "District 3, Worton (Betterton)", "Billings CCD", "District E" and "Canteen
township" — administrative bookkeeping, not the name of a place anyone lives in. Falling
back to it would have raised coverage from 75% to 100% while re-contaminating the field with
a new kind of wrong string, which is the exact mistake being repaired here. Points with
neither an Incorporated Place nor a CDP get `None` and are labelled as unknown.

    .venv/bin/python -m pipeline.spine.place          # all venues, resumable
    .venv/bin/python -m pipeline.spine.place 50       # first 50, for a smoke test
"""

from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests

from ..common.http import USER_AGENT

OUTPUT = Path(__file__).resolve().parent.parent / "output"
VENUES = OUTPUT / "venues_full.json"
CACHE = OUTPUT / "venue_place.json"

GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# Order is the fallback order. See the module docstring for why County Subdivisions is not
# on this list despite being the layer that would close the remaining 25%.
LAYERS = ["Incorporated Places", "Census Designated Places"]

WORKERS = 8
TIMEOUT_S = 30
ATTEMPTS = 3

# The Census appends the legal type to the name: "New London city", "Kings Point village",
# "Pepperdine University CDP". Stripped so the field holds what a person would write on an
# envelope. Anchored to the end and space-separated so it cannot eat part of a real name —
# "Village of Lakewood" and "Cityscape" survive, "Carson city" becomes "Carson".
TYPE_SUFFIX = re.compile(
    r"\s+(city|town|village|borough|township|municipality|CDP|"
    r"city and borough|consolidated government|unified government|"
    r"metro government|urban county|corporation|plantation|gore|grant|location)$",
    re.IGNORECASE,
)


def clean_name(raw: str) -> str:
    """"New London city" -> "New London". Applied once; names are not re-stripped."""
    return TYPE_SUFFIX.sub("", raw).strip()


def _lookup(session: requests.Session, lng: float, lat: float) -> tuple[Optional[str], str]:
    """The municipality containing one point, and which Census layer answered.

    `(None, "no_place")` is a real answer rather than a failure. Unincorporated land outside
    any CDP genuinely has no place name — a racetrack in open country, a ski resort on
    national forest — and recording that is the whole point of not falling through to
    County Subdivisions.
    """
    params = {
        "x": lng,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": ",".join(LAYERS),
        "format": "json",
    }
    last: Optional[Exception] = None
    for _ in range(ATTEMPTS):
        try:
            resp = session.get(GEOCODER, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            geo = resp.json()["result"]["geographies"] or {}
            # Matched case-insensitively for the same reason the ZCTA lookup is: the
            # geocoder does not spell its layer keys consistently across vintages, and
            # matching literally turns "spelled differently" into "no result", which is
            # indistinguishable from "this point is nowhere".
            lowered = {k.lower(): v for k, v in geo.items()}
            for layer in LAYERS:
                hits = lowered.get(layer.lower()) or []
                if hits:
                    return clean_name(hits[0]["NAME"]), layer.lower().replace(" ", "_")
            return None, "no_place"
        except Exception as exc:  # noqa: BLE001 - network and shape errors are both retryable
            last = exc
    raise RuntimeError(f"geocoder failed for ({lng}, {lat}): {last}")


def run(limit: Optional[int] = None) -> dict:
    venues = json.loads(VENUES.read_text())
    if limit:
        venues = venues[:limit]

    done = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [v for v in venues if v["venue_id"] not in done and v.get("lat") and v.get("lng")]
    print(f"{len(venues)} venues, {len(done)} already resolved, {len(todo)} to fetch",
          flush=True)

    lock = threading.Lock()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    def resolve(venue: dict) -> None:
        name, source = _lookup(session, venue["lng"], venue["lat"])
        with lock:
            done[venue["venue_id"]] = {"city": name, "city_source": source}
            # Flushed on a cadence rather than per venue: rewriting a 7.5k-entry file 7.5k
            # times is quadratic, and losing at most 200 lookups to a crash is cheap.
            if len(done) % 200 == 0:
                CACHE.write_text(json.dumps(done, indent=1, sort_keys=True))
                print(f"  {len(done)} resolved", flush=True)

    try:
        if todo:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(resolve, todo))
    finally:
        # Written even when a lookup raises. The run is only resumable if the work it did
        # before failing survives; without this a crash at venue 7,000 costs all 7,000.
        CACHE.write_text(json.dumps(done, indent=1, sort_keys=True))

    counts: dict = {}
    for rec in done.values():
        counts[rec["city_source"]] = counts.get(rec["city_source"], 0) + 1
    return counts


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    counts = run(limit)
    print(f"\nwrote {CACHE.relative_to(OUTPUT.parent.parent)}")
    for source, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {source:<26} {n}")


if __name__ == "__main__":
    main()
