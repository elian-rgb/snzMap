"""Phase 0 — Wikidata half of the venue spine.

Wikidata is primary for stadiums/arenas because it is the only free source that carries
the two things the extraction step needs: (a) venues that no longer exist, and (b) former
names with date ranges. A 2001 article says "Enron Field"; a 2015 article says "Minute Maid
Park". Both must resolve to one venue_id or the tenure table fragments.

Strategy is deliberately two-stage: one cheap query to enumerate the QID census, then
chunked VALUES queries for detail. Paging a `P31/P279*` query with LIMIT/OFFSET is not
stable across requests; a fixed QID list is.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..common.http import PoliteSession

ENDPOINT = "https://query.wikidata.org/sparql"
CHUNK = 250

# Q1076486 sports venue — the superclass that pulls in stadium, ballpark, arena,
# racetrack, etc. via P279*. Convention centers are not sports venues; see overpass.py.
SPORTS_VENUE = "wd:Q1076486"

CENSUS_QUERY = f"""
SELECT DISTINCT ?venue WHERE {{
  ?venue wdt:P31/wdt:P279* {SPORTS_VENUE} ;
         wdt:P17 wd:Q30 .
}}
"""

# Second census pass, keyed on function rather than type.
#
# Typing on Wikidata is inconsistent: American Family Field (Milwaukee) is P31
# "architectural structure", so the P279* walk above never reaches it, and the MLB
# spot-check caught the omission. P115 ("home venue" of a team) is a far better proxy for
# the thing we actually care about — a building where a team plays is a building with a
# concession contract — and it is independent of how a contributor happened to type it.
HOME_VENUE_QUERY = """
SELECT DISTINCT ?venue WHERE {
  ?team wdt:P115 ?venue .
  ?venue wdt:P17 wd:Q30 .
}
"""

DETAIL_QUERY = """
SELECT ?venue ?venueLabel ?type ?typeLabel ?coord ?inception ?dissolved
       ?city ?cityLabel ?state ?stateLabel ?capacity ?osm ?image WHERE {
  VALUES ?venue { %s }
  OPTIONAL { ?venue wdt:P31 ?type }
  OPTIONAL { ?venue wdt:P625 ?coord }
  OPTIONAL { ?venue wdt:P571 ?inception }
  OPTIONAL { ?venue wdt:P576 ?dissolved }
  OPTIONAL { ?venue wdt:P131 ?city }
  OPTIONAL { ?venue wdt:P131+ ?state . ?state wdt:P31 wd:Q35657 . }
  OPTIONAL { ?venue wdt:P1083 ?capacity }
  OPTIONAL { ?venue wdt:P402 ?osm }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Naming-rights history. P1448 (official name) carries P580/P582 qualifiers on venues
# whose sponsor changed. This is the highest-value field in the whole spine.
NAME_HISTORY_QUERY = """
SELECT ?venue ?name ?start ?end WHERE {
  VALUES ?venue { %s }
  ?venue p:P1448 ?stmt .
  ?stmt ps:P1448 ?name .
  OPTIONAL { ?stmt pq:P580 ?start }
  OPTIONAL { ?stmt pq:P582 ?end }
}
"""

# Undated fallback aliases. Wikidata contributors often record a former stadium name as a
# plain altLabel with no dates. Undated is still matchable; it just cannot disambiguate
# two operators at the same venue in different decades, so we keep the dates separate.
ALTLABEL_QUERY = """
SELECT ?venue ?alt WHERE {
  VALUES ?venue { %s }
  ?venue skos:altLabel ?alt .
  FILTER(LANG(?alt) = "en")
}
"""

session = PoliteSession(name="wikidata", min_interval_s=1.5, timeout_s=300)


def _validate_sparql(body: str) -> None:
    """WDQS sometimes answers 200 with a body truncated at a buffer boundary."""
    json.loads(body)["results"]["bindings"]


def _run(query: str, label: str) -> list[dict]:
    body = session.post(
        ENDPOINT,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        label=label,
        validate=_validate_sparql,
    )
    return json.loads(body)["results"]["bindings"]


def _val(row: dict, key: str) -> str | None:
    cell = row.get(key)
    if not cell:
        return None
    value = cell.get("value")
    return value or None


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _parse_point(wkt: str | None) -> tuple[float, float] | tuple[None, None]:
    if not wkt:
        return None, None
    m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", wkt)
    if not m:
        return None, None
    return float(m.group(2)), float(m.group(1))  # lat, lng


def _parse_date(raw: str | None) -> str | None:
    """Wikidata dates arrive as +1995-04-26T00:00:00Z, sometimes with 00 month/day
    to signal reduced precision. Normalize to YYYY-MM-DD, zeroes -> 01."""
    if not raw:
        return None
    m = re.match(r"[+-]?(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        return None
    year, month, day = m.groups()
    if year == "0000":
        return None
    return f"{year}-{month if month != '00' else '01'}-{day if day != '00' else '01'}"


def _split_packed_alias(raw: str) -> list[str]:
    """One altLabel often holds several names.

    Hard Rock Stadium's altLabel is the single string
    "Pro Player Stadium, Dolphin Stadium, Sun Life Stadium" — three former names packed
    into one field. Left unsplit, an article saying "Sun Life Stadium" matches nothing.

    Splitting on commas is only safe because venue names rarely contain them; the guards
    below skip fragments too short to be a venue name and keep the original string too,
    so a genuinely comma-containing name is not lost.
    """
    parts = [p.strip() for p in re.split(r"[,;]|\s+/\s+", raw)]
    parts = [p for p in parts if len(p) >= 6]
    if len(parts) <= 1:
        return [raw.strip()]
    return [raw.strip()] + parts


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_census() -> list[str]:
    by_type = {_qid(_val(r, "venue")) for r in _run(CENSUS_QUERY, "census")}
    by_use = {_qid(_val(r, "venue")) for r in _run(HOME_VENUE_QUERY, "census_home_venue")}
    print(f"  {len(by_type)} by type, {len(by_use)} by home-venue "
          f"({len(by_use - by_type)} of those missed by the type walk)")
    return sorted(by_type | by_use)


def fetch_details(qids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, chunk in enumerate(_chunks(qids, CHUNK)):
        values = " ".join(f"wd:{q}" for q in chunk)
        rows = _run(DETAIL_QUERY % values, f"detail_{i:03d}")
        for row in rows:
            qid = _qid(_val(row, "venue"))
            rec = out.setdefault(
                qid,
                {
                    "wikidata_qid": qid,
                    "canonical_name": None,
                    "types": set(),
                    "lat": None,
                    "lng": None,
                    "opened_date": None,
                    "closed_date": None,
                    "city": None,
                    "state": None,
                    "capacity": None,
                    "osm_id": None,
                },
            )
            label = _val(row, "venueLabel")
            # The label service falls back to the QID when no English label exists.
            if label and not re.fullmatch(r"Q\d+", label):
                rec["canonical_name"] = label
            type_label = _val(row, "typeLabel")
            if type_label and not re.fullmatch(r"Q\d+", type_label):
                rec["types"].add(type_label)

            lat, lng = _parse_point(_val(row, "coord"))
            if lat is not None:
                rec["lat"], rec["lng"] = lat, lng
            rec["opened_date"] = rec["opened_date"] or _parse_date(_val(row, "inception"))
            rec["closed_date"] = rec["closed_date"] or _parse_date(_val(row, "dissolved"))
            rec["city"] = rec["city"] or _val(row, "cityLabel")
            rec["state"] = rec["state"] or _val(row, "stateLabel")
            cap = _val(row, "capacity")
            if cap and rec["capacity"] is None:
                try:
                    rec["capacity"] = int(float(cap))
                except ValueError:
                    pass
            rec["osm_id"] = rec["osm_id"] or _val(row, "osm")
        print(f"  details chunk {i}: {len(out)} venues so far")
    for rec in out.values():
        rec["types"] = sorted(rec["types"])
    return out


def fetch_aliases(qids: list[str]) -> dict[str, list[dict]]:
    """Returns venue_qid -> [{name, start_date, end_date}], dated entries first."""
    aliases: dict[str, list[dict]] = {}
    seen: dict[str, set] = {}

    for i, chunk in enumerate(_chunks(qids, CHUNK)):
        values = " ".join(f"wd:{q}" for q in chunk)
        for row in _run(NAME_HISTORY_QUERY % values, f"names_{i:03d}"):
            qid = _qid(_val(row, "venue"))
            name = _val(row, "name")
            if not name:
                continue
            entry = {
                "name": name,
                "start_date": _parse_date(_val(row, "start")),
                "end_date": _parse_date(_val(row, "end")),
                "dated": bool(_val(row, "start") or _val(row, "end")),
            }
            key = (name.lower(), entry["start_date"], entry["end_date"])
            if key in seen.setdefault(qid, set()):
                continue
            seen[qid].add(key)
            aliases.setdefault(qid, []).append(entry)
        print(f"  name-history chunk {i}: {sum(len(v) for v in aliases.values())} entries")

    for i, chunk in enumerate(_chunks(qids, CHUNK)):
        values = " ".join(f"wd:{q}" for q in chunk)
        for row in _run(ALTLABEL_QUERY % values, f"alt_{i:03d}"):
            qid = _qid(_val(row, "venue"))
            raw = _val(row, "alt")
            if not raw:
                continue
            for name in _split_packed_alias(raw):
                # Skip if a dated statement already covers this name; dated wins.
                if any(a["name"].lower() == name.lower() for a in aliases.get(qid, [])):
                    continue
                key = (name.lower(), None, None)
                if key in seen.setdefault(qid, set()):
                    continue
                seen[qid].add(key)
                aliases.setdefault(qid, []).append(
                    {"name": name, "start_date": None, "end_date": None, "dated": False}
                )
        print(f"  altLabel chunk {i}: {sum(len(v) for v in aliases.values())} entries")

    for entries in aliases.values():
        entries.sort(key=lambda e: (not e["dated"], e["start_date"] or "", e["name"]))
    return aliases


def main(out_path: Path | None = None) -> Path:
    out_path = out_path or Path(__file__).resolve().parent.parent / "output" / "spine_wikidata.json"
    print("Fetching Wikidata census of US sports venues...")
    qids = fetch_census()
    print(f"  {len(qids)} QIDs")

    print("Fetching venue detail...")
    details = fetch_details(qids)

    print("Fetching name history + aliases...")
    aliases = fetch_aliases(qids)

    for qid, rec in details.items():
        rec["aliases"] = aliases.get(qid, [])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(list(details.values()), indent=1))
    dated = sum(1 for r in details.values() for a in r["aliases"] if a["dated"])
    print(
        f"Wrote {len(details)} venues -> {out_path}\n"
        f"  with coords: {sum(1 for r in details.values() if r['lat'] is not None)}\n"
        f"  defunct (closed_date set): {sum(1 for r in details.values() if r['closed_date'])}\n"
        f"  dated former names: {dated}"
    )
    return out_path


if __name__ == "__main__":
    main()
