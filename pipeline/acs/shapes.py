"""Cut the national ZCTA boundary files down to the ZCTAs that actually hold a venue.

The console draws ACS context as a shaded area, and that needs polygons. The Census ships
them nationally — 33,144 for the 2010 definition and 33,791 for the 2020 one, 188 MB of
shapefile between them. Only 4,087 distinct ZCTAs contain a venue, so 88% of that is area
this map has nothing to say about.

Shipping only the 12% is a claim, not just a saving. A choropleth covering the whole country
invites the reading "every ZCTA was measured"; one covering only venue ZCTAs says what is
true, which is that the layer describes *the neighbourhood around each venue* and nowhere
else. Blank map is then correct rather than missing — there is no venue there.

Two vintages are emitted and never merged. ACS 5-year vintages through 2020 are tabulated
on 2010-Census ZCTAs and later ones on 2020-Census ZCTAs, and the Census *reuses codes* for
redrawn areas. 20001 in 2015 and 20001 in 2024 are different polygons with the same name, so
a single shape file keyed on the code would silently draw one decade's boundaries under the
other decade's numbers. The console switches file at the same year `load.py` switches ZCTA.

Coordinates come out of the shapefile in NAD83 (the .prj says GCS_North_American_1983) and
are written as-is. RFC 7946 asks for WGS84; the two differ by one to two metres in CONUS,
which is far below the resolution of a ZCTA boundary drawn at 1:500,000, but the file says
which datum it is rather than claiming the one it does not have.

    .venv/bin/python -m pipeline.acs.shapes
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable, Optional

import shapefile  # pyshp — pure Python, reads .shp/.dbf without GDAL

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
RAW = ROOT / "raw" / "zcta_shapes"

ZCTA_CACHE = OUT / "venue_zcta.json"

# vintage -> (zip, basename inside it, the field holding the 5-digit code)
SOURCES = {
    2010: ("cb_2019_us_zcta510_500k.zip", "cb_2019_us_zcta510_500k", "ZCTA5CE10"),
    2020: ("cb_2020_us_zcta520_500k.zip", "cb_2020_us_zcta520_500k", "ZCTA5CE20"),
}

# The 2010-Census ZCTAs are carried by the 2019 cartographic-boundary vintage, which is the
# last one published on them. Naming the file by its download year and the geography by the
# census it came from keeps that from looking like an off-by-one.
VINTAGE_SOURCE_NOTE = (
    "2010-Census ZCTAs are taken from the 2019 cartographic boundary file, the last vintage "
    "published on them; 2020-Census ZCTAs from the 2020 file."
)

# ~55 m at the equator. The boundaries are already generalized to 1:500,000, so this is a
# second pass aimed only at the redundant vertices that survive it.
#
# Chosen by measuring against the containment gate rather than by eye. Venues that fall
# outside their own ZCTA polygon, and the size of both files together:
#
#     tolerance   outside   size
#     0.0         50        30.5 MB     <- no simplification at all
#     0.0002      51        27.1 MB
#     0.0005      55        21.8 MB     <- here
#     0.001       101       15.4 MB
#
# 50 is the floor: those venues are outside even with every vertex kept, because the ACS
# tabulation geography the geocoder answered from and this 1:500,000 cartographic
# generalization of it are different products. 0.0005 buys 8.7 MB for five more, and the
# next step down the list doubles them, so this is the knee.
TOLERANCE = 0.0005

# ~1 m. Beyond this the digits describe nothing a 1:500,000 boundary knows.
PRECISION = 5


def _perpendicular(pt, start, end) -> float:
    """Distance from `pt` to the segment start-end, in degrees."""
    (x, y), (x1, y1), (x2, y2) = pt, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker, iterative so a 40,000-vertex coastline cannot blow the stack."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, index = 0.0, first
        for i in range(first + 1, last):
            d = _perpendicular(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def _rings(shape) -> list[list[tuple[float, float]]]:
    """Split a pyshp polygon into its rings, in file order."""
    parts = list(shape.parts) + [len(shape.points)]
    return [
        [(float(x), float(y)) for x, y in shape.points[parts[i]: parts[i + 1]]]
        for i in range(len(parts) - 1)
    ]


def _signed_area(ring: list) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _round(ring: list) -> list:
    return [[round(x, PRECISION), round(y, PRECISION)] for x, y in ring]


def _close(ring: list) -> list:
    return ring if ring[0] == ring[-1] else ring + [ring[0]]


def to_geometry(shape, tolerance: float) -> Optional[dict[str, Any]]:
    """A pyshp polygon as GeoJSON Polygon/MultiPolygon, or None if nothing survived.

    Shapefiles distinguish outer rings from holes by winding order, not by nesting, and
    GeoJSON needs the nesting. The shapefile convention is that an outer ring is clockwise,
    which is a *negative* shoelace area — the opposite of the usual maths convention, and
    easy to get backwards. Getting it backwards does not crash: every outer ring after the
    first is attached to the previous polygon as a hole, so the file still renders, just
    with the wrong areas punched out. It was caught by the point-in-polygon gate, which put
    1,427 venues outside their own ZCTA.

    A ZCTA with detached islands is a MultiPolygon; one with a lake is a Polygon with a
    hole. Dropping either would redraw the geography, so both are kept.

    Rings are reversed on the way out: RFC 7946 asks for counterclockwise outer rings and
    clockwise holes, which is the reverse of the shapefile convention in both cases.
    """
    polygons: list[list[list]] = []
    for ring in _rings(shape):
        simplified = simplify(ring, tolerance)
        # Three distinct points plus the closing repeat. Anything less has no interior and
        # would be an invalid GeoJSON ring.
        if len(simplified) < 4:
            continue
        ready = _close(_round(simplified))[::-1]
        if len(ready) < 4:
            continue
        if _signed_area(ring) < 0 or not polygons:
            polygons.append([ready])
        else:
            polygons[-1].append(ready)

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": [[r for r in p] for p in polygons]}


def needed() -> dict[int, set[str]]:
    """The ZCTA codes each vintage has to draw, straight off the geocode cache."""
    if not ZCTA_CACHE.exists():
        raise FileNotFoundError(
            f"{ZCTA_CACHE.name} not found — run pipeline.acs.geocode first"
        )
    assignments = json.loads(ZCTA_CACHE.read_text())
    wanted: dict[int, set[str]] = {2010: set(), 2020: set()}
    for a in assignments.values():
        for vintage in (2010, 2020):
            code = a.get(f"zcta_{vintage}")
            if code:
                wanted[vintage].add(code)
    return wanted


def _reader(zip_path: Path, base: str) -> shapefile.Reader:
    z = zipfile.ZipFile(zip_path)
    return shapefile.Reader(
        shp=io.BytesIO(z.read(f"{base}.shp")),
        dbf=io.BytesIO(z.read(f"{base}.dbf")),
        shx=io.BytesIO(z.read(f"{base}.shx")),
    )


def build(vintage: int, tolerance: float = TOLERANCE) -> dict[str, Any]:
    zip_name, base, field = SOURCES[vintage]
    path = RAW / zip_name
    if not path.exists():
        raise FileNotFoundError(f"boundary file missing: {path}")

    wanted = needed()[vintage]
    reader = _reader(path, base)
    names = [f[0] for f in reader.fields[1:]]
    index = names.index(field)

    features = []
    seen: set[str] = set()
    empty: list[str] = []
    for record, shape in zip(reader.iterRecords(), reader.iterShapes()):
        code = str(record[index]).strip()
        if code not in wanted or code in seen:
            continue
        geometry = to_geometry(shape, tolerance)
        if geometry is None:
            # Kept as a named absence rather than skipped quietly: a ZCTA that simplified to
            # nothing is a tolerance bug, and it would otherwise look like a code the Census
            # never published.
            empty.append(code)
            continue
        seen.add(code)
        features.append(
            {
                "type": "Feature",
                "properties": {"zcta": code, "zcta_vintage": vintage},
                "geometry": geometry,
            }
        )

    # Codes the geocoder assigned that the boundary file has no polygon for. Reported, never
    # silently dropped — the console cannot shade these and a reader deserves the count.
    missing = sorted(wanted - seen)

    return {
        "type": "FeatureCollection",
        "zcta_vintage": vintage,
        "crs_note": "Coordinates are NAD83 (EPSG:4269) as published, not WGS84.",
        "source_note": VINTAGE_SOURCE_NOTE,
        "scope_note": (
            "Only ZCTAs containing at least one venue in the spine are included. Blank areas "
            "mean no venue is located there, not that the neighbourhood was not measured."
        ),
        "simplify_tolerance_deg": tolerance,
        "zctas_requested": len(wanted),
        "zctas_drawn": len(features),
        "zctas_without_polygon": missing,
        "zctas_emptied_by_simplify": sorted(empty),
        "features": features,
    }


def emit(vintage: int) -> tuple[Path, dict[str, Any]]:
    payload = build(vintage)
    path = OUT / f"acs_zcta_{vintage}.geojson"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return path, payload


def main() -> None:
    for vintage in sorted(SOURCES):
        path, payload = emit(vintage)
        size = path.stat().st_size / 1e6
        print(
            f"{path.name}: {payload['zctas_drawn']:,} of "
            f"{payload['zctas_requested']:,} requested ZCTAs, {size:.1f} MB"
        )
        if payload["zctas_without_polygon"]:
            codes = payload["zctas_without_polygon"]
            print(f"  no polygon in the boundary file: {len(codes)} -> {codes[:10]}")
        if payload["zctas_emptied_by_simplify"]:
            print(f"  emptied by simplify: {payload['zctas_emptied_by_simplify']}")


if __name__ == "__main__":
    main()
