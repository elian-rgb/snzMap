"""Phase 0 — OSM half of the venue spine.

Two jobs, both things Wikidata does badly:

  1. Convention centers. They are not sports venues, so the Wikidata query misses them
     entirely, and Wikidata's coverage of them is thin. OSM tags them directly.
  2. Coordinate cross-check for the sports venues. OSM geometry is generally more current
     than Wikidata's point, and OSM objects carry a `wikidata` tag we can join on for free.
     We only pull OSM objects that already have that tag — that keeps the query small and
     the join unambiguous.

OSM will not tell us about demolished venues (they get deleted from the map), which is
exactly why Wikidata is primary for the stadium/arena census.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..common.http import PoliteSession

# The main overpass-api.de instance 504s on any US-wide query under normal load; the
# kumi mirror answers the same queries in ~90s. Try in order.
ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Bounding boxes beat `area["ISO3166-1"="US"]`, which alone is enough to blow the timeout.
BBOXES = {
    "conus": "24.5,-125.0,49.5,-66.9",
    "ak": "51.0,-170.0,72.0,-129.0",
    "hi": "18.5,-161.0,22.5,-154.5",
}

# Tag-only. A US-wide regex on `name` requires a full scan and 502s on every mirror.
CONVENTION_QUERY = """
[out:json][timeout:300];
(
  nwr["amenity"="conference_centre"](%(bbox)s);
  nwr["amenity"="exhibition_centre"](%(bbox)s);
  nwr["building"="convention_centre"](%(bbox)s);
  nwr["tourism"="convention_centre"](%(bbox)s);
);
out center tags;
"""

# Only wikidata-tagged venues: this is a join key, not a census.
SPORTS_XCHECK_QUERY = """
[out:json][timeout:300];
(
  nwr["leisure"="stadium"]["wikidata"](%(bbox)s);
  nwr["building"="stadium"]["wikidata"](%(bbox)s);
  nwr["leisure"="sports_centre"]["wikidata"](%(bbox)s);
);
out center tags;
"""

# `amenity=conference_centre` is used in OSM for anything with a meeting room — church
# camps, lodge halls, hotel annexes. The spine wants venues a national contractor would
# bid on. Keep the tag hits that either name themselves as a convention/expo facility or
# carry the more specific building/tourism tag.
CONVENTION_NAME_RE = re.compile(
    r"convention|exposition|expo cent|exhibition|civic cent|fairgrounds|"
    r"trade cent|coliseum|congress cent",
    re.I,
)
SPECIFIC_TAGS = {
    ("building", "convention_centre"),
    ("tourism", "convention_centre"),
    ("amenity", "exhibition_centre"),
}

session = PoliteSession(name="overpass", min_interval_s=8.0, timeout_s=400)


def _validate_overpass(body: str) -> None:
    json.loads(body)["elements"]


def _run(query: str, label: str) -> list[dict]:
    last = None
    for endpoint in ENDPOINTS:
        try:
            body = session.post(
                endpoint, data={"data": query}, label=label, validate=_validate_overpass
            )
            return json.loads(body)["elements"]
        except Exception as exc:  # noqa: BLE001 - fall through to the next mirror
            last = exc
            print(f"  {endpoint} failed ({exc}); trying next mirror")
    raise RuntimeError(f"all Overpass mirrors failed for {label}: {last}")


def _run_all_bboxes(query_template: str, label: str) -> list[dict]:
    elements: dict[tuple, dict] = {}
    for region, bbox in BBOXES.items():
        rows = _run(query_template % {"bbox": bbox}, f"{label}_{region}")
        print(f"  {label}/{region}: {len(rows)} elements")
        for el in rows:
            elements[(el["type"], el["id"])] = el
    return list(elements.values())


def _coords(el: dict) -> tuple[float | None, float | None]:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center") or {}
    return center.get("lat"), center.get("lon")


def _normalize(el: dict) -> dict | None:
    tags = el.get("tags") or {}
    name = tags.get("name")
    lat, lng = _coords(el)
    if not name or lat is None:
        return None
    return {
        "osm_id": f"{el['type']}/{el['id']}",
        "canonical_name": name,
        "lat": lat,
        "lng": lng,
        "city": tags.get("addr:city"),
        "state": tags.get("addr:state"),
        "wikidata_qid": tags.get("wikidata"),
        "start_date": tags.get("start_date"),
        "alt_names": [
            v
            for k, v in tags.items()
            if k in ("alt_name", "old_name", "official_name", "short_name")
            for v in v.split(";")
        ],
        "osm_tags": {
            k: v
            for k, v in tags.items()
            if k in ("amenity", "building", "leisure", "tourism", "operator")
        },
    }


def main(out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Overpass: convention centers...")
    raw_conv = [r for r in (_normalize(e) for e in _run_all_bboxes(CONVENTION_QUERY, "convention")) if r]
    conv = [
        r
        for r in raw_conv
        if CONVENTION_NAME_RE.search(r["canonical_name"])
        or any(r["osm_tags"].get(k) == v for k, v in SPECIFIC_TAGS)
    ]
    for rec in conv:
        rec["venue_type"] = "convention_center"
    conv_path = out_dir / "spine_overpass_convention.json"
    conv_path.write_text(json.dumps(conv, indent=1))
    (out_dir / "spine_overpass_convention_rejected.json").write_text(
        json.dumps([r for r in raw_conv if r not in conv], indent=1)
    )
    print(
        f"  {len(conv)} kept of {len(raw_conv)} tag hits -> {conv_path}\n"
        f"  (rejects saved for review — 'conference_centre' in OSM covers church camps too)"
    )

    print("Overpass: wikidata-tagged sports venues (coordinate cross-check)...")
    xcheck = [r for r in (_normalize(e) for e in _run_all_bboxes(SPORTS_XCHECK_QUERY, "xcheck")) if r]
    xcheck = [r for r in xcheck if r["wikidata_qid"]]
    x_path = out_dir / "spine_overpass_xcheck.json"
    x_path.write_text(json.dumps(xcheck, indent=1))
    print(f"  {len(xcheck)} wikidata-linked OSM venues -> {x_path}")

    return conv_path, x_path


if __name__ == "__main__":
    main()
