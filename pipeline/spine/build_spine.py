"""Phase 0 — merge Wikidata + OSM into the venue spine.

Output is the denominator for the whole project. Once this file exists, a gap in the
tenure table is no longer ambiguous: every spine venue either has tenure rows or is a
documented gap in the hunt log.

Two design decisions worth stating:

  * `venue_id` is derived from the *source key* (`wd-Q1193671`), not from the name.
    Names change — Enron Field became Minute Maid Park became Daikin Park. A foreign key
    that moves when a sponsor changes is not a foreign key.
  * `match_keys` is precomputed here rather than in the extractor. Venue matching then
    becomes a dict lookup instead of fuzzy string work at extraction time, and the alias
    date ranges stay attached so a 2001 "Enron Field" hit can be sanity-checked against
    the year the article was published.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "output"
ROOT = Path(__file__).resolve().parent.parent
PLACES = OUT / "venue_place.json"

STATE_ABBREV = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY", "District of Columbia": "DC",
}

# Wikidata hands back a bag of P31 labels per venue. Collapse to one venue_type, most
# specific first — a "baseball venue" that is also a "stadium" is a ballpark.
TYPE_RULES = [
    ("convention_center", ("convention", "exhibition", "conference", "congress cent")),
    ("ballpark", ("baseball",)),
    ("racetrack", ("race track", "racetrack", "racing circuit", "speedway", "motorsport",
                   "horse racing", "dragstrip", "street circuit", "racecourse")),
    ("arena", ("arena", "indoor", "ice rink", "velodrome", "basketball venue", "hockey",
               "multi-purpose hall", "tennis venue", "coliseum")),
    ("stadium", ("stadium", "football venue", "soccer", "bowl", "multi-purpose sports")),
    ("amphitheater", ("amphitheat", "concert hall", "music venue", "theatre", "theater")),
    ("golf_course", ("golf", "country club")),
    ("aquatic_center", ("aquatic", "swimming", "water park", "natatorium")),
    ("ski_resort", ("ski resort", "ski area", "ski jumping", "ski ")),
    ("recreation", ("gym", "fitness", "health club", "skatepark", "climbing",
                    "sports centre", "sports center", "athletic training", "marina",
                    "sports field", "training facility")),
]

# The scope in SNZ_PLAN_v2 Phase 0 is stadiums, arenas and major convention centers.
# Wikidata's "sports venue" tree also drags in ski resorts, skateparks, marinas and campus
# gyms. Those are not deleted — deleting them would quietly shrink the denominator, and
# they may matter later — but they are marked out of scope so the map and the coverage
# math default to the venues where contracts actually happen.
IN_SCOPE_TYPES = {
    "stadium", "arena", "ballpark", "convention_center", "racetrack", "amphitheater",
}

# Nouns for a *kind* of building. A match key made of nothing but these does not identify a
# venue, it identifies a category — and it fires on ordinary prose. They appear because
# short_forms() strips the distinguishing part off ("The Ballpark at Hallsville" -> "The
# Ballpark" -> `ballpark`) and because packed aliases split a place off the end ("Water
# World, Colorado" -> `colorado`). Six venues owned the key `ballpark`.
#
# Qualifiers are deliberately absent — memorial, municipal, civic, university, state, fair,
# county, old, new. "Memorial Stadium" is a real name that reporters print, and prose never
# says "the memorial stadium", so it stays matchable even though both its words are common.
# An earlier draft listed them here and made 63 in-scope venues unreachable, Fair Park and
# 21 Memorial Stadiums among them. `ball` is absent for a blunter reason: Ball Arena is the
# old Pepsi Center, and listing it deleted Denver's biggest venue from the scan.
VENUE_TYPE_WORDS = {
    "amphitheater", "amphitheatre", "arena", "armory", "auditorium", "ballpark", "beach",
    "bowl", "center", "centre", "coliseum", "colosseum", "complex", "convention", "dome",
    "event", "events", "expo", "exposition", "fairground", "fairgrounds", "field",
    "fieldhouse", "forum", "garden", "gardens", "grounds", "gymnasium", "hall", "palace",
    "park", "pavilion", "raceway", "speedway", "sports", "sportsplex", "stadium", "yard",
}


# Informal venue names collide with ordinary vocabulary: `pond` is the Honda Center, `jake`
# is Progressive Field, `igloo` is the Civic Arena, `cell` is Comiskey. These are the names
# reporters actually use, so a stoplist would throw away the best keys in the spine. What
# separates them from prose is case — a paper writes "the Pond" and "a pond" — so keys that
# are also English words are flagged here and matched case-sensitively at scan time.
DICT_PATHS = [Path("/usr/share/dict/words"), Path("/usr/dict/words")]


def load_english_words() -> set[str]:
    for path in DICT_PATHS:
        if path.exists():
            return {w.strip().lower() for w in path.read_text(errors="ignore").split()}
    print("  ! no system word list; nickname keys will match case-insensitively")
    return set()


def is_type_phrase(key: str) -> bool:
    """True when the key is only category nouns — `ballpark`, `convention center`, `expo
    hall`. False for `memorial stadium` or `fair park`, which are names."""
    tokens = key.split()
    return bool(tokens) and all(t in VENUE_TYPE_WORDS for t in tokens)

ABBREV_TO_STATE = {v: k for k, v in STATE_ABBREV.items()}


# Wikidata's P115 ("home venue of a team") sometimes names the city rather than the
# building, so the census that fixed American Family Field also swept in Boston, Chicago and
# New York City as venues. Left in, an article with a Chicago dateline gets offered
# "Chicago" as a candidate venue and can be assigned its venue_id — a wrong foreign key on a
# real event, which is worse than no key at all.
#
# The test is on the P31 labels, not the name: Fair Park, Park City, Jackson Park and Taos
# Ski Valley are real venues whose names are also places, and the US Naval Academy is
# genuinely typed as a census-designated place *and* a naval academy.
SETTLEMENT_TYPE = re.compile(
    r"\b(?:cit(?:y|ies)|town|village|municipality|borough|township|hamlet|county|parish|"
    r"metropolis|megacity|county seat|census-designated place|human settlement|"
    r"unincorporated community|neighbou?rhood|suburb|locality|capital)\b",
    re.I,
)


def is_settlement(type_labels: list[str]) -> bool:
    """True only when *every* type label says settlement. One venue-ish label is enough to
    keep the record — a place that is both a town and a ski resort is still a ski resort."""
    return bool(type_labels) and all(SETTLEMENT_TYPE.search(t) for t in type_labels)


def classify(type_labels: list[str]) -> str:
    joined = " ; ".join(t.lower() for t in type_labels)
    for venue_type, needles in TYPE_RULES:
        if any(n in joined for n in needles):
            return venue_type
    return "other"


def match_key(name: str) -> str:
    """Normalized form used to join an article's venue string to the spine.

    Aggressive on purpose: articles print 'the Coors Field', 'Coors Field.', 'COORS FIELD'.
    Deliberately does NOT strip sponsor words — 'Enron Field' and 'Minute Maid Park' must
    stay distinct keys, since which one appears is itself dating evidence.

    Accents are folded rather than dropped. Wikidata spells it "Henry B. González
    Convention Center"; American wire copy spells it "Gonzalez". Without the fold the
    two normalize to 'gonz lez' and 'gonzalez' and never meet.
    """
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", s)
    s = re.sub(r"\bthe\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  ! missing {path.name} — skipping")
        return []
    return json.loads(path.read_text())


def build_from_wikidata(rows: list[dict], xcheck_by_qid: dict[str, dict]) -> list[dict]:
    venues = []
    settlements = []
    for r in rows:
        qid = r["wikidata_qid"]
        name = r.get("canonical_name")
        if not name:
            continue  # no English label: nothing an article could ever match against

        if is_settlement(r.get("types") or []):
            settlements.append({"venue_id": f"wd-{qid}", "canonical_name": name,
                                "types": r.get("types")})
            continue

        lat, lng = r.get("lat"), r.get("lng")
        osm = xcheck_by_qid.get(qid)
        coord_delta_km = None
        coord_source = "wikidata" if lat is not None else None
        if osm:
            if lat is None:
                lat, lng, coord_source = osm["lat"], osm["lng"], "osm"
            else:
                coord_delta_km = round(haversine_km(lat, lng, osm["lat"], osm["lng"]), 3)

        aliases = list(r.get("aliases") or [])
        if not any(a["name"].lower() == name.lower() for a in aliases):
            aliases.insert(0, {"name": name, "start_date": None, "end_date": None, "dated": False})
        if osm:
            for alt in osm.get("alt_names") or []:
                alt = alt.strip()
                if alt and not any(a["name"].lower() == alt.lower() for a in aliases):
                    aliases.append(
                        {"name": alt, "start_date": None, "end_date": None, "dated": False}
                    )

        state = r.get("state")
        venues.append(
            {
                "venue_id": f"wd-{qid}",
                "canonical_name": name,
                "aliases": aliases,
                "venue_type": classify(r.get("types") or []),
                "city": r.get("city"),
                "state": STATE_ABBREV.get(state, state),
                "lat": lat,
                "lng": lng,
                "opened_date": r.get("opened_date"),
                "closed_date": r.get("closed_date"),
                "capacity": r.get("capacity"),
                "wikidata_qid": qid,
                "osm_id": (osm or {}).get("osm_id") or r.get("osm_id"),
                "spine_source": "wikidata",
                "coord_source": coord_source,
                "coord_delta_km": coord_delta_km,
            }
        )

    if settlements:
        # Kept on disk rather than only counted — a census filter that silently eats records
        # is how the denominator quietly shrinks.
        (OUT / "spine_settlements_rejected.json").write_text(json.dumps(settlements, indent=2))
        print(f"  dropped {len(settlements)} settlements typed as venues "
              f"-> output/spine_settlements_rejected.json")
    return venues


def build_from_convention(rows: list[dict], seen_qids: set) -> list[dict]:
    venues = []
    for r in rows:
        qid = r.get("wikidata_qid")
        if qid and qid in seen_qids:
            continue  # already in the spine from the Wikidata pass
        name = r["canonical_name"]
        state = r.get("state")
        venues.append(
            {
                "venue_id": f"osm-{r['osm_id'].replace('/', '-')}",
                "canonical_name": name,
                "aliases": [{"name": name, "start_date": None, "end_date": None, "dated": False}]
                + [
                    {"name": a.strip(), "start_date": None, "end_date": None, "dated": False}
                    for a in (r.get("alt_names") or [])
                    if a.strip() and a.strip().lower() != name.lower()
                ],
                "venue_type": "convention_center",
                "city": r.get("city"),
                "state": STATE_ABBREV.get(state, state),
                "lat": r["lat"],
                "lng": r["lng"],
                "opened_date": r.get("start_date"),
                "closed_date": None,
                "capacity": None,
                "wikidata_qid": qid,
                "osm_id": r["osm_id"],
                "spine_source": "osm",
                "coord_source": "osm",
                "coord_delta_km": None,
            }
        )
    return venues


def dedupe_by_proximity(venues: list[dict]) -> list[dict]:
    """Two OSM objects for one building (a node and its way) become one venue.
    Same normalized name within 1km = same place."""
    kept: list[dict] = []
    index: dict[str, list[dict]] = {}
    dropped = 0
    for v in venues:
        key = match_key(v["canonical_name"])
        clash = None
        for other in index.get(key, []):
            if (
                v["lat"] is not None
                and other["lat"] is not None
                and haversine_km(v["lat"], v["lng"], other["lat"], other["lng"]) < 1.0
            ):
                clash = other
                break
        if clash:
            dropped += 1
            clash.setdefault("merged_ids", []).append(v["venue_id"])
            continue
        index.setdefault(key, []).append(v)
        kept.append(v)
    print(f"  deduped {dropped} near-duplicate records")
    return kept


def split_packed_alias(raw: str) -> list[str]:
    """One name field often holds several names.

    OSM's `old_name` on Hard Rock Stadium is the single string
    "Pro Player Stadium, Dolphin Stadium, Sun Life Stadium" — three former names in one
    tag. Left unsplit, an article saying "Sun Life Stadium" matches nothing.

    Splitting on commas is safe here only because venue names rarely contain them; the
    original string is kept as well, so a genuinely comma-bearing name is not lost.
    """
    parts = [p.strip() for p in re.split(r"[,;]|\s+/\s+", raw) if len(p.strip()) >= 6]
    return [raw.strip()] + parts if len(parts) > 1 else [raw.strip()]


# Convention centers carry the longest gap between the name on the deed and the name in the
# paper, because their legal names absorb every function the building serves: Sacramento's
# is the "Sacramento Convention Center Complex", Tacoma's the "Greater Tacoma Convention and
# Trade Center", St. Louis's the "America's Center Convention Complex". A reporter writes
# two words plus the city. These rules collapse the tail back to that.
#
# Each is anchored to an explicit convention phrase. An earlier draft stripped a leading
# "Greater " unconditionally and turned "Greater Nevada Field" — a credit union's naming
# rights deal — into "Nevada Field", which is a different (nonexistent) ballpark.
_CONVENTION_RULES = [
    (r"\s+Convention\s+(?:and|&)\s+(?:Entertainment|Trade|Exhibition|Exposition|Visitors?)\s+Cent(?:er|re)$", " Convention Center"),
    (r"\s+(?:Entertainment|Trade|Exhibition|Exposition)\s+(?:and|&)\s+Convention\s+Cent(?:er|re)$", " Convention Center"),
    (r"\s+Convention\s+Cent(?:er|re)\s+Complex$", " Convention Center"),
    (r"\s+Convention\s+Complex$", " Convention Center"),
    (r"\s+International(?=\s+Convention\s+Cent(?:er|re)$)", ""),
    (r"^Greater\s+(?=.*\bConvention\s+Cent(?:er|re)\b)", ""),
]


def convention_forms(name: str) -> list[str]:
    """Printed forms of a convention center's legal name. Applied to every venue, but the
    anchors mean only convention names can match."""
    out: list[str] = []
    current = name
    for _ in range(len(_CONVENTION_RULES)):
        collapsed = current
        for pattern, replacement in _CONVENTION_RULES:
            collapsed = re.sub(pattern, replacement, collapsed, flags=re.I).strip()
        if collapsed == current:
            break
        current = collapsed
        if len(current) >= 6 and current not in out:
            out.append(current)

    # "America's Center Convention Complex" is never printed with either of those last two
    # words. Only "Convention Complex" is droppable outright — dropping "Convention Center
    # Complex" would leave a bare city name.
    bare = re.sub(r"\s+Convention\s+Complex$", "", name, flags=re.I).strip()
    if bare != name and len(bare) >= 6 and bare not in out:
        out.append(bare)
    return out


def short_forms(name: str, city: str | None = None) -> list[str]:
    """Shorter names an article would plausibly print for the same venue.

    Wikidata's canonical label is often the full legal name — "Angel Stadium of Anaheim",
    "Rangers Ballpark in Arlington", "Charles Schwab Field Omaha" — while a newspaper
    writes "Angel Stadium". Without these variants the MLB spot-check misses live venues.

    Only locative tails are stripped, and a bare trailing city only when it matches the
    venue's own city field, so this cannot invent a name for an unrelated place. Sponsor
    words are deliberately left alone: which sponsor appears is itself evidence of when
    an article was written.
    """
    out = []
    trimmed = re.sub(r"\s+(of|at|in)\s+[A-Z][\w.'-]*(\s+[A-Z][\w.'-]*)*$", "", name).strip()
    if trimmed != name and len(trimmed) >= 6:
        out.append(trimmed)

    if city:
        without_city = re.sub(rf"\s+{re.escape(city)}$", "", trimmed or name).strip()
        if without_city != (trimmed or name) and len(without_city) >= 6:
            out.append(without_city)

    # Buildings named after people carry the full name on the facade and the surname in the
    # newspaper: "Jacob K. Javits Convention Center" is always "the Javits Center". The
    # middle initial is the tell that this is a person, which stops the rule from firing on
    # "Los Angeles Memorial Coliseum". Without it most of the country's person-named
    # convention centers are unreachable from the name a reporter actually types.
    surname = re.sub(r"^[A-Z][\w'-]+(\s+[A-Z]\.)+\s+", "", name).strip()
    if surname != name and len(surname) >= 6:
        out.append(surname)
        contracted = re.sub(r"\s+Convention(\s+&|\s+and)?(\s+\w+)?\s+Cent(er|re)$", " Center", surname)
        if contracted != surname and len(contracted) >= 6:
            out.append(contracted)

    for variant in [name, *out]:
        for form in convention_forms(variant):
            if form not in out:
                out.append(form)
    return out


def usable_key(key: str, venue: dict, place_names: set[str]) -> bool:
    """Does this key name *this* venue, or just describe a building or a place?

    Applied to everything except the canonical name, so a venue really called "Convention
    Center" keeps that key — dropping a venue's only key would make it unreachable.
    """
    if not key or is_type_phrase(key):
        return False
    # "Water World, Colorado" splits to "Colorado"; Wikidata lists a bare "Denver" as an
    # alias of the University of Denver Soccer Stadium, and "St. Louis" as one of Francis
    # Olympic Field. A key that is exactly a city or state the spine already knows about is
    # geography, not a venue's identity — and it fires on every dateline in the corpus.
    if key in place_names:
        return False
    return True


def attach_match_keys(venues: list[dict]) -> None:
    place_names = set()
    for v in venues:
        for place in (v.get("city"), v.get("state"), ABBREV_TO_STATE.get(v.get("state") or "")):
            if place:
                place_names.add(match_key(place))
    place_names.discard("")

    dropped = 0
    for v in venues:
        keys = {}
        canonical = match_key(v["canonical_name"])
        for a in v["aliases"]:
            for name in split_packed_alias(a["name"]):
                for variant in [name, *short_forms(name, v.get("city"))]:
                    k = match_key(variant)
                    if not k:
                        continue
                    if k != canonical and not usable_key(k, v, place_names):
                        dropped += 1
                        continue
                    # A dated alias must not be overwritten by an undated short form.
                    if k not in keys:
                        keys[k] = {"start_date": a["start_date"], "end_date": a["end_date"]}
        v["match_keys"] = keys
    print(f"  dropped {dropped} generic keys (category nouns, bare geography)")

    english = load_english_words()
    cased = 0
    for v in venues:
        for key, window in v["match_keys"].items():
            if " " not in key and key in english:
                window["cased"] = True
                cased += 1
    print(f"  flagged {cased} keys that are also English words (match case-sensitively)")


def report_ambiguity(venues: list[dict]) -> dict[str, list[str]]:
    """Match keys shared by more than one venue. The extractor must not silently pick one
    of these — it needs city/state context or a needs_review flag."""
    owners: dict[str, list[str]] = {}
    for v in venues:
        for k in v["match_keys"]:
            owners.setdefault(k, []).append(v["venue_id"])
    return {k: ids for k, ids in owners.items() if len(ids) > 1}


def apply_places(venues: list[dict]) -> dict:
    """Replace Wikidata's `city` with the municipality the venue's coordinate actually sits in.

    `wdt:P131` is a chain — venue -> village -> town -> county -> state — and which rung a
    given Wikidata item happens to point at is an editorial accident. Read one level deep and
    unfiltered, it put the venue's own *state* in `city` for 2,480 of 6,884 mapped venues: the
    US Coast Guard Academy's city was "Connecticut". That is worse than a blank, because a
    blank is a gap a reader can see. See pipeline/spine/place.py for why the fix reads the
    coordinate through the Census geocoder instead of re-querying Wikidata.

    Applied here — after dedupe, before `attach_match_keys` — because the cache is keyed on
    the venue_id that survives a merge, and because two things downstream read `city` and both
    get better with a correct one: `short_forms` strips a trailing city off a venue name, and
    `match_keys` drops a key that is exactly a city the spine knows about.

    The override is unconditional where the geocoder answered, and *also* unconditional where
    it answered `None`: an unincorporated point outside any CDP has no municipality, and
    keeping "Connecticut" there because it is better than nothing is the whole bug. Venues the
    geocoder never saw — no coordinate, or added since the last pass — keep what they had and
    are counted, so a stale cache shows up as a number rather than as silence.
    """
    if not PLACES.exists():
        raise SystemExit(
            f"missing {PLACES.relative_to(ROOT.parent)} — run: "
            ".venv/bin/python -m pipeline.spine.place"
        )
    places = json.loads(PLACES.read_text())
    counts: dict[str, int] = {}
    for v in venues:
        rec = places.get(v["venue_id"])
        if rec is None:
            # Left as-is and labelled, so a venue still carrying a Wikidata city is
            # distinguishable from one the Census confirmed.
            v["city_source"] = "wikidata_unverified" if v.get("city") else "none"
        else:
            v["city"] = rec["city"]
            v["city_source"] = rec["city_source"]
        counts[v["city_source"]] = counts.get(v["city_source"], 0) + 1
    return counts


def main() -> None:
    wd = load(OUT / "spine_wikidata.json")
    conv = load(OUT / "spine_overpass_convention.json")
    xcheck = load(OUT / "spine_overpass_xcheck.json")

    xcheck_by_qid = {r["wikidata_qid"]: r for r in xcheck if r.get("wikidata_qid")}
    print(f"Loaded: {len(wd)} wikidata, {len(conv)} convention, {len(xcheck)} osm-xcheck")

    venues = build_from_wikidata(wd, xcheck_by_qid)
    venues += build_from_convention(conv, {v["wikidata_qid"] for v in venues})
    venues = dedupe_by_proximity(venues)
    place_counts = apply_places(venues)
    attach_match_keys(venues)

    ambiguous = report_ambiguity(venues)
    for v in venues:
        v["name_is_ambiguous"] = any(k in ambiguous for k in v["match_keys"])
        # A generically-typed venue that seats a crowd is in scope regardless of type;
        # American Family Field is P31 "architectural structure" on Wikidata.
        v["in_scope"] = v["venue_type"] in IN_SCOPE_TYPES or (v["capacity"] or 0) >= 5000

    # match_keys stays out of the map payload: it is an extraction-side lookup table and
    # roughly doubles the file the browser has to download.
    map_omit = {"lat", "lng", "match_keys", "merged_ids"}
    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": v["venue_id"],
                "geometry": {"type": "Point", "coordinates": [v["lng"], v["lat"]]},
                "properties": {k: val for k, val in v.items() if k not in map_omit},
            }
            for v in venues
            if v["lat"] is not None
        ],
    }
    (OUT / "venues.geojson").write_text(json.dumps(geo))

    fields = [
        "venue_id", "canonical_name", "venue_type", "city", "city_source", "state", "lat", "lng",
        "opened_date", "closed_date", "capacity", "wikidata_qid", "osm_id",
        "spine_source", "coord_delta_km", "in_scope", "name_is_ambiguous", "alias_count",
        "dated_alias_count", "all_aliases",
    ]
    with (OUT / "venues.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for v in venues:
            w.writerow(
                {
                    **v,
                    "alias_count": len(v["aliases"]),
                    "dated_alias_count": sum(1 for a in v["aliases"] if a.get("dated")),
                    "all_aliases": " | ".join(a["name"] for a in v["aliases"]),
                }
            )

    (OUT / "venues_full.json").write_text(json.dumps(venues, indent=1))
    (OUT / "spine_ambiguous_names.json").write_text(json.dumps(ambiguous, indent=1))

    no_coords = sum(1 for v in venues if v["lat"] is None)
    no_state = sum(1 for v in venues if not v["state"])
    far = [v for v in venues if (v["coord_delta_km"] or 0) > 2]
    by_type: dict[str, int] = {}
    for v in venues:
        by_type[v["venue_type"]] = by_type.get(v["venue_type"], 0) + 1

    print(
        f"\nSPINE: {len(venues)} venues -> output/venues.geojson ({len(geo['features'])} mappable)\n"
        f"  in scope (stadium/arena/ballpark/convention/racetrack or 5k+ seats): "
        f"{sum(1 for v in venues if v['in_scope'])}\n"
        f"  by type: {dict(sorted(by_type.items(), key=lambda x: -x[1]))}\n"
        f"  defunct (closed_date set): {sum(1 for v in venues if v['closed_date'])}\n"
        f"  venues with dated former names: {sum(1 for v in venues if any(a.get('dated') for a in v['aliases']))}\n"
        f"  missing coords: {no_coords}   missing state: {no_state}\n"
        f"  wikidata/osm coord disagreement >2km: {len(far)}\n"
        f"  ambiguous match keys: {len(ambiguous)}\n"
        f"  city from census: {dict(sorted(place_counts.items(), key=lambda x: -x[1]))}"
    )


if __name__ == "__main__":
    main()
