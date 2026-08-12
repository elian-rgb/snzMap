"""Gate for the ZCTA shape layer — is each venue inside the area it is being shaded by?

The failure this exists to catch is a quiet one. A choropleth always looks authoritative:
it is a filled polygon with a number attached, and nothing about a wrong polygon looks
wrong. Three ways it can lie here, and one check each:

  * the shape is the wrong vintage      -> the two files must not be interchangeable
  * the shape is the wrong place        -> each venue must fall inside its own ZCTA
  * the shape is missing and unreported -> every requested code must be drawn or listed

The point-in-polygon check is the one that matters most, and it is checking something the
rest of the pipeline cannot. `geocode.py` asked the Census which ZCTA a coordinate is in;
this asks whether the polygon we are about to *draw* agrees. Those come from different
Census products — an API lookup against tabulation geography, and a 1:500,000 cartographic
generalization of it — so they can disagree at the edges, and the generalization is exactly
what the console renders.

    .venv/bin/python -m pipeline.acs.check_shapes
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Callable

from .shapes import OUT, SOURCES, ZCTA_CACHE

CHECKS: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []


def check(label: str) -> Callable[[Callable[[dict[str, Any]], bool]], Any]:
    def wrap(fn: Callable[[dict[str, Any]], bool]) -> Callable[[dict[str, Any]], bool]:
        CHECKS.append((label, fn))
        return fn

    return wrap


def _ring_contains(point: tuple[float, float], ring: list) -> bool:
    """Ray casting. `ring` is a closed list of [x, y]."""
    x, y = point
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                inside = not inside
    return inside


def contains(geometry: dict[str, Any], point: tuple[float, float]) -> bool:
    """Point in a GeoJSON Polygon or MultiPolygon, holes subtracted."""
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    for rings in polygons:
        if not rings:
            continue
        if _ring_contains(point, rings[0]) and not any(
            _ring_contains(point, hole) for hole in rings[1:]
        ):
            return True
    return False


def load() -> dict[str, Any]:
    layers = {}
    for vintage in SOURCES:
        path = OUT / f"acs_zcta_{vintage}.geojson"
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found — run pipeline.acs.shapes")
        layers[vintage] = json.loads(path.read_text())
    return {
        "layers": layers,
        "assignments": json.loads(ZCTA_CACHE.read_text()),
        "venues": json.loads((OUT / "venues_full.json").read_text()),
    }


@check("both shape files are present and non-trivial")
def _loaded(ctx: dict[str, Any]) -> bool:
    # An empty or near-empty file would satisfy almost every other check by vacuum, so the
    # floor is asserted before anything else runs.
    return all(
        len(layer["features"]) > 3000 for layer in ctx["layers"].values()
    )


@check("every requested ZCTA is drawn, or named as missing")
def _accounted(ctx: dict[str, Any]) -> bool:
    for layer in ctx["layers"].values():
        drawn = len(layer["features"])
        missing = len(layer["zctas_without_polygon"])
        if drawn + missing != layer["zctas_requested"]:
            return False
    return True


@check("no ZCTA is drawn twice in one vintage")
def _unique(ctx: dict[str, Any]) -> bool:
    for layer in ctx["layers"].values():
        codes = [f["properties"]["zcta"] for f in layer["features"]]
        if len(codes) != len(set(codes)):
            return False
    return True


@check("every ring is closed and has an interior")
def _rings_valid(ctx: dict[str, Any]) -> bool:
    for layer in ctx["layers"].values():
        for feature in layer["features"]:
            g = feature["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for rings in polys:
                for ring in rings:
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        return False
    return True


@check("each feature is labelled with the vintage of the file it is in")
def _labelled(ctx: dict[str, Any]) -> bool:
    return all(
        all(f["properties"]["zcta_vintage"] == vintage for f in layer["features"])
        for vintage, layer in ctx["layers"].items()
    )


@check("the two vintages are genuinely different geographies")
def _vintages_differ(ctx: dict[str, Any]) -> bool:
    """Guards against emitting the same boundaries twice under two names.

    The ZCTAs shared by both files are the interesting ones: the Census reuses codes for
    redrawn areas, so a code present in both should mostly *not* have identical geometry.
    If it always did, the vintage switch in the console would be decoration.
    """
    a = {f["properties"]["zcta"]: f["geometry"] for f in ctx["layers"][2010]["features"]}
    b = {f["properties"]["zcta"]: f["geometry"] for f in ctx["layers"][2020]["features"]}
    shared = set(a) & set(b)
    if not shared:
        return False
    changed = sum(1 for code in shared if a[code] != b[code])
    return changed > len(shared) * 0.5


# Measured, not guessed. 50 venue-vintage pairs fall outside their own polygon even with
# zero simplification, because the geocoder answered from ACS tabulation geography and this
# is a 1:500,000 cartographic generalization of it; the shipping tolerance adds five more.
# The budget is that measurement plus a little headroom. It exists to catch a regression:
# a reversed ring-winding test put 1,427 venues outside, and a check that only asked "is it
# zero" would have been switched off as unattainable instead of catching that.
OUTSIDE_BUDGET = 60

# Every known miss is a venue on water — marinas, a yacht club, a dive site — whose
# coordinate sits offshore of a boundary that follows the shoreline. The median is 13 m and
# the worst is 1.36 km. A venue assigned genuinely the wrong ZCTA would be much further out,
# so distance is the check that tells an artifact from an error.
OUTSIDE_MAX_KM = 2.0


@check("venues outside their own ZCTA stay within the measured budget")
def _outside_budget(ctx: dict[str, Any]) -> bool:
    return len(outside(ctx)) <= OUTSIDE_BUDGET


@check("no venue is far from the ZCTA that shades it")
def _outside_is_marginal(ctx: dict[str, Any]) -> bool:
    return all(km <= OUTSIDE_MAX_KM for km, *_ in distances(ctx))


def _segment_distance(point: tuple[float, float], ring: list) -> float:
    """Smallest distance from `point` to a closed ring, in degrees."""
    x, y = point
    best = float("inf")
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            d = math.hypot(x - x1, y - y1)
        else:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
        best = min(best, d)
    return best


def distances(ctx: dict[str, Any]) -> list[tuple[float, str, int, str]]:
    """(km outside, venue_id, vintage, zcta) for each miss, nearest first."""
    by_code = {
        vintage: {f["properties"]["zcta"]: f["geometry"] for f in layer["features"]}
        for vintage, layer in ctx["layers"].items()
    }
    venues = {v["venue_id"]: v for v in ctx["venues"]}
    rows = []
    for venue_id, vintage, code in outside(ctx):
        venue = venues[venue_id]
        lng, lat = float(venue["lng"]), float(venue["lat"])
        geometry = by_code[vintage][code]
        polygons = (
            [geometry["coordinates"]]
            if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        )
        degrees = min(
            _segment_distance((lng, lat), ring) for poly in polygons for ring in poly
        )
        rows.append(
            (degrees * 111.32 * math.cos(math.radians(lat)), venue_id, vintage, code)
        )
    return sorted(rows)


def outside(ctx: dict[str, Any]) -> list[tuple[str, int, str]]:
    """(venue_id, vintage, zcta) for every venue that is not inside its own polygon."""
    by_code = {
        vintage: {f["properties"]["zcta"]: f["geometry"] for f in layer["features"]}
        for vintage, layer in ctx["layers"].items()
    }
    misses = []
    for venue in ctx["venues"]:
        lat, lng = venue.get("lat"), venue.get("lng")
        if not (lat and lng):
            continue
        assignment = ctx["assignments"].get(venue["venue_id"])
        if not assignment:
            continue
        for vintage in SOURCES:
            code = assignment.get(f"zcta_{vintage}")
            if not code:
                continue
            geometry = by_code[vintage].get(code)
            if geometry is None:
                continue
            if not contains(geometry, (float(lng), float(lat))):
                misses.append((venue["venue_id"], vintage, code))
    return misses


def main() -> int:
    ctx = load()
    failed = 0
    for label, fn in CHECKS:
        try:
            ok = fn(ctx)
        except Exception as exc:  # a check that errors is a check that failed
            ok = False
            label = f"{label}  [{type(exc).__name__}: {exc}]"
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        failed += not ok

    rows = distances(ctx)
    total = sum(len(layer["features"]) for layer in ctx["layers"].values())
    print(f"\n{total:,} polygons across {len(ctx['layers'])} vintages")
    print(
        f"{len(rows)} of {OUTSIDE_BUDGET} budgeted venue-vintage pairs fall outside "
        f"their own ZCTA"
    )
    if rows:
        km = [r[0] for r in rows]
        print(
            f"  distance outside: median {statistics.median(km) * 1000:,.0f} m, "
            f"max {max(km):.2f} km (limit {OUTSIDE_MAX_KM} km)"
        )
        names = {v["venue_id"]: v.get("canonical_name") for v in ctx["venues"]}
        for dist, venue_id, vintage, code in rows[-5:]:
            print(f"    {dist:6.2f} km  {vintage} {code}  {names.get(venue_id)}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
