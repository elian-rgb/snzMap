"""WHD wage-and-hour enforcement, resolved to operators — deliberately NOT to venues.

WHISARD is the Wage and Hour Division's investigation database: every closed WHD case,
naming the employer, its establishment address, the industry, the workers affected, the
back wages owed and the penalties assessed. 367,893 cases. For the operators this project
tracks, a few hundred.

WHY THERE IS NO VENUE JOIN HERE. The federal award loader ties a row to a venue only when
the award *description names the venue* and the ZIP agrees. WHISARD has no such field — a
case knows an employer and a street address, never "Busch Stadium". Joining on ZIP alone
was measured before this module was written: 179 candidate cases fall in a ZIP that
contains a spine venue, and those 179 touch 420 distinct venues. Only 57 sit in a ZIP with
exactly one venue, and even those are coincidence rather than evidence — an Aramark unit in
a ZIP could be the school, the hospital or the office park, and WHISARD does not say. One
Aramark case in Raleigh 27607 would have attached itself to nine North Carolina State
venues at once. So this emits an operator profile and the console shows it as one. A
back-wage figure printed beside a named stadium that did not earn it is the exact failure
this project is built to avoid.

WHY THE MATCHING IS HERE AND NOT IN SQL. Two substring traps were found by measuring, and
both would have printed a large wrong number:

  `%FOODA%`         matched fourteen Foodarama/ShopRite supermarkets, a McDonald's and a
                    cafe, and no real Fooda at all — carrying $429,880 in penalties that
                    belonged to a grocery chain.
  `%SPORT SERVICE%` matched "tranSPORT SERVICES" — 84 ambulance, trucking and medical
                    transport firms, carrying $2,187,898 in back wages. Delaware North's
                    real food-service total is $4,648. A 470x overstatement.

Matching therefore runs on *tokens with boundaries*, in Python where `check_rules` can test
it, and both traps are regression cases in that gate. The SQL below is deliberately loose:
it over-collects on purpose so that rejections are counted here rather than never fetched.

PROVENANCE. The data is public-domain federal data, but it is read from an independent
mirror — a Datasette rebuild at labordata.bunkum.us (source: github.com/labordata/whd-
compliance), not from dol.gov. DOL's own API at apiprod.dol.gov requires a registered key.
The mirror is named in the emitted profile and on screen; it is not passed off as the
primary source.

    .venv/bin/python -m pipeline.labor.load --refresh   # re-query the mirror
    .venv/bin/python -m pipeline.labor.load             # rebuild from the snapshot
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

from ..schema import KNOWN_OPERATORS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "whd"
OUT = ROOT / "output"

SNAPSHOT = "whd_cases.json"
MANIFEST = "manifest.json"

MIRROR = "https://labordata.bunkum.us/whisard.json"
MIRROR_NOTE = (
    "Independent Datasette mirror of the DOL Wage and Hour Division's WHISARD database "
    "(rebuilt by github.com/labordata/whd-compliance). Public-domain federal data, but "
    "not served by dol.gov — DOL's own API requires a registered key."
)

# Loose on purpose. Anything this pulls that is not an operator gets rejected by
# `match_operator` and *counted* in the profile's `rejected` block, which is the drift
# alarm: if a future load starts rejecting names it used to accept, the count moves.
CANDIDATE_SQL = """
select case_id, legal_name, trade_nm, naic_cd, naics_code_description,
       street_addr_1_txt, cty_nm, st_cd, zip_cd,
       findings_start_date, findings_end_date,
       bw_atp_amt, ee_atp_cnt, cmp_assd, case_violtn_cnt, flsa_repeat_violator
from (select *, upper(coalesce(legal_name,'') || ' ' || coalesce(trade_nm,'')) as nm from cases)
where nm like '%ARAMARK%' or nm like '%ARAMAK%' or nm like '%SODEX%'
   or nm like '%SDH SERVICES%' or nm like '%SDH EDUCATION%'
   or nm like '%COMPASS%' or nm like '%CANTEEN%' or nm like '%CHARTWELLS%'
   or nm like '%BON APPETIT%' or nm like '%EUREST%'
   or nm like '%MORRISON%' or nm like '%FLIK%' or nm like '%RESTAURANT ASSOCIATES%'
   or nm like '%WOLFGANG PUCK%' or nm like '%DELAWARE NORTH%'
   or nm like '%SPORTSERVICE%' or nm like '%SPORT SERVICE%'
   or nm like '%CENTERPLATE%' or nm like '%VOLUME SERVICES%'
   or nm like '%LEVY%' or nm like '%LEGENDS%' or nm like '%WHITSONS%'
   or nm like '%THOMPSON HOSPITALITY%' or nm like '%METZ%' or nm like '%FOODA%'
   or nm like '%OAK VIEW%' or nm like '%SPECTRA%'
order by case_id
"""

# Legal-form noise. Stripped so "Aramark Services, Inc." and "Aramark Services LLC" are the
# same name, which is what the crosswalk keys are written against.
SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "lc", "lp", "l p", "llp", "lllp", "ltd",
    "limited", "corp", "corporation", "co", "company", "plc", "partnership",
    "subsidiaries", "subsidiary", "et al", "the",
}

# Written out rather than derived from `schema.KNOWN_OPERATORS`, and that is the whole
# lesson of this table. Deriving it injected the bare canonical names — "Legends",
# "Compass", "Levy", "Morrison", "Canteen" — which are ordinary English words. Measured on
# the real corpus, bare "legends" matched 25 cases and every single one was a local sports
# bar: Legends Patio Grill, Legends Smokehouse, Legends Sports Pub. Zero were Legends
# Hospitality. Bare "restaurant associates" pulled in a Burger King, a Persian restaurant
# and a tavern; bare "morrison" pulled in a Florida buffet chain unrelated to Morrison
# Healthcare; bare "canteen" pulled in the Canteen Bar & Grille.
#
# So every alias below has to be specific enough to be safe as a *leading* match. Where the
# operator's real name is a common word, the alias carries the qualifier that makes it a
# company: `legends hospitality`, not `legends`.
ALIASES: dict[str, str] = {
    "aramark": "Aramark",
    "aramak": "Aramark",  # a spelling WHD actually recorded

    "sodexo": "Sodexo",
    "sodexho": "Sodexo",
    "sodexomagic": "Sodexo",
    "sodexo live": "Sodexo",
    "sdh services": "Sodexo",
    "sdh education": "Sodexo",

    "compass group": "Compass",
    "chartwells": "Compass",
    "eurest": "Compass",
    "flik international": "Compass",
    "restaurant associates": "Compass",
    "wolfgang puck catering": "Compass",
    "bon appetit management": "Compass",
    "morrison management": "Compass",
    "morrison healthcare": "Compass",
    "morrison senior living": "Compass",
    "morrison community living": "Compass",
    "morrison dining": "Compass",
    "canteen correctional": "Compass",
    "canteen service": "Compass",
    "canteen services": "Compass",
    "canteen vending": "Compass",
    "canteen food": "Compass",
    "canteen dining": "Compass",

    "levy premium foodservice": "Levy",
    "levy premium food service": "Levy",
    "levy restaurants": "Levy",
    "levy world": "Levy",

    "delaware north": "Delaware North",
    "sportservice": "Delaware North",
    "sportservices": "Delaware North",
    "sport service": "Delaware North",

    "centerplate": "Centerplate",
    "center plate": "Centerplate",
    "volume services america": "Centerplate",
    "volume services": "Centerplate",

    "legends hospitality": "Legends",
    "whitsons": "Whitsons Culinary Group",
    "thompson hospitality": "Thompson Hospitality",
    "metz culinary": "Metz Culinary Management",
    "oak view group": "Oak View Group",
    "ovg hospitality": "Oak View Group",
    "spectra food services": "Oak View Group",
    "fooda": "Fooda",
}

# Safe to find *anywhere* in the name, not just leading. "Metroplex SportService, Inc." and
# "Columbus Sport Service, LLC" are real Delaware North units whose names lead with the
# city, so a leading-only rule would discard them.
#
# `sport service` is in here despite being the alias that caused the worst false positive,
# because token matching is what fixes it: "Contract Transport Services" tokenizes to
# ("contract", "transport", "services") and never yields the adjacent pair
# ("sport", "service"). Substring matching is what was broken, not this alias.
DISTINCTIVE = {
    "aramark", "aramak", "sodexo", "sodexho", "sdh services", "sdh education",
    "chartwells", "eurest", "centerplate", "sportservice", "sportservices",
    "sport service", "delaware north", "whitsons", "thompson hospitality",
    "volume services america", "legends hospitality", "levy premium foodservice",
    "metz culinary", "wolfgang puck catering",
}

# NAICS 722 is food service. The rest is the same corporation doing something else: Aramark
# launders uniforms, Sodexo runs facilities, and several of these conglomerates run
# ambulances. Kept and labelled rather than dropped — a filtered-away row nobody can see is
# how a total stops adding up — but only `food_service` reaches the headline figures.
ADJACENT_NAICS = {
    "561210", "56121",   # facilities support services
    "561720", "56172",   # janitorial
    "454210", "45421",   # vending machine operators
    "81233", "812331", "812332",  # linen / uniform supply, industrial launderers
    "454390",            # other direct selling
}

# Sodexo's remote-sites arm, excluded from the federal awards for the same reason: it is
# catering, but for offshore rigs and remote camps, not at any venue on this map. Kiki's
# call there, applied here so the two money layers count the same company the same way.
REMOTE_SITE_TOKENS = ("offshore and remote site", "remote sites", "offshore & remote")


def _norm(s: Any) -> str:
    """Lowercase, drop punctuation, collapse space. 'd/b/a' and '&' become separators."""
    t = str(s or "").lower()
    t = t.replace("&", " and ")
    t = re.sub(r"\bd/?b/?a\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_name(s: Any) -> str:
    """Normalized name with legal-form words removed from anywhere in it.

    Not just the end: WHD records "Compass Group USA, Inc. d/b/a Eurest" and "Foodarama
    Supermarkets Inc. & Subsidiaries", where the legal form sits in the middle and a
    trailing-only trim leaves "inc" wedged between two real words. Stripping everywhere
    can in principle eat a genuine word — a company actually called "Company Cafes" — but
    no such name appears in this corpus, and leaving the noise in makes two spellings of
    the same employer look like two employers.
    """
    parts = [p for p in _norm(s).split() if p not in SUFFIXES]
    while parts and parts[-1] == "and":
        parts.pop()
    return " ".join(parts)


def unknown_operators() -> set[str]:
    """Operators named here that the project's crosswalk does not recognise.

    The alias table is hand-written, but it does not get its own opinion about *who exists*
    — `schema.KNOWN_OPERATORS` remains the authority, and `check_rules` fails if this is
    ever non-empty. One deliberate divergence: `schema.SUB_BRANDS` maps `levy restaurants`
    to Compass, since Compass owns Levy. Here Levy stays Levy, because the employer of
    record on a WHD case is the Levy entity and the tenure layer names Levy — folding it
    into Compass would make the two layers disagree on screen about the same venue.
    """
    return set(ALIASES.values()) - set(KNOWN_OPERATORS)


def _leads_with(name: str, alias: str) -> bool:
    return name == alias or name.startswith(alias + " ")


def _contains_tokens(name: str, alias: str) -> bool:
    """Alias appears as a whole-token run. This is what stops 'tranSPORT SERVICES'."""
    return re.search(rf"(?:^| ){re.escape(alias)}(?:$| )", name) is not None


def match_operator(legal_name: Any, trade_nm: Any) -> tuple[Optional[str], str]:
    """(operator, how). `how` is 'trade_name' | 'name_leading' | 'distinctive' | 'no_match'.

    Longest alias first so "levy premium foodservice" wins over "levy", and
    "delaware north" over nothing.
    """
    legal, trade = clean_name(legal_name), clean_name(trade_nm)
    order = sorted(ALIASES, key=len, reverse=True)

    for alias in order:
        if trade and _leads_with(trade, alias):
            return ALIASES[alias], "trade_name"
    for alias in order:
        if legal and _leads_with(legal, alias):
            return ALIASES[alias], "name_leading"
    for alias in order:
        if alias in DISTINCTIVE and (
            (legal and _contains_tokens(legal, alias))
            or (trade and _contains_tokens(trade, alias))
        ):
            return ALIASES[alias], "distinctive"
    return None, "no_match"


def line_of_business(naics: Any) -> str:
    code = str(naics or "").strip()
    if code.startswith("722"):
        return "food_service"
    if code in ADJACENT_NAICS or code.startswith("8123"):
        return "adjacent"
    return "other_line_of_business"


def judge(row: dict[str, Any]) -> dict[str, Any]:
    """Attach an operator and a scope decision to one WHD case. Nothing is dropped."""
    op, how = match_operator(row.get("legal_name"), row.get("trade_nm"))
    lob = line_of_business(row.get("naic_cd"))
    both = f"{_norm(row.get('legal_name'))} {_norm(row.get('trade_nm'))}"

    if op is None:
        scope = "rejected_not_an_operator"
    elif any(t in both for t in REMOTE_SITE_TOKENS):
        scope = "excluded_remote_site"
    elif lob == "food_service":
        scope = "in_scope"
    else:
        scope = "excluded_other_line"

    return {
        **row,
        "operator": op,
        "matched_how": how,
        "line_of_business": lob,
        "scope": scope,
    }


def fetch(url: str = MIRROR, sql: str = CANDIDATE_SQL) -> list[dict[str, Any]]:
    q = urllib.parse.urlencode({"sql": sql, "_shape": "array", "_size": "max"})
    req = urllib.request.Request(
        f"{url}?{q}", headers={"User-Agent": "SNZMap/0.1 (research; contact via repo)"}
    )
    with urllib.request.urlopen(req, timeout=120) as fh:
        payload = fh.read()
    rows = json.loads(payload)
    if isinstance(rows, dict):
        raise SystemExit(f"mirror returned an error rather than rows: {str(rows)[:300]}")
    return rows


def snapshot(raw: Path = RAW) -> list[dict[str, Any]]:
    raw.mkdir(parents=True, exist_ok=True)
    rows = fetch()
    body = json.dumps(rows, indent=1, sort_keys=True, default=str)
    (raw / SNAPSHOT).write_text(body)
    (raw / MANIFEST).write_text(json.dumps({
        "source_url": MIRROR,
        "source_note": MIRROR_NOTE,
        "sql": CANDIDATE_SQL.strip(),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "rows": len(rows),
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
    }, indent=1) + "\n")
    return rows


def load_snapshot(raw: Path = RAW) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path, man = raw / SNAPSHOT, raw / MANIFEST
    if not path.exists():
        raise SystemExit(
            f"no WHD snapshot at {path}.\n"
            "  Run: .venv/bin/python -m pipeline.labor.load --refresh"
        )
    return json.loads(path.read_text()), json.loads(man.read_text())


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _year(v: Any) -> Optional[int]:
    s = str(v or "")[:4]
    return int(s) if s.isdigit() else None


def profile(judged: Iterable[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    judged = list(judged)
    kept = [r for r in judged if r["scope"] == "in_scope"]

    by_op: dict[str, dict[str, Any]] = {}
    for r in kept:
        d = by_op.setdefault(r["operator"], {
            "operator": r["operator"], "cases": 0, "back_wages": 0.0,
            "employees_due_back_wages": 0, "civil_penalties": 0.0,
            "repeat_violator_cases": 0, "first_year": None, "last_year": None,
        })
        d["cases"] += 1
        d["back_wages"] += _num(r.get("bw_atp_amt"))
        d["employees_due_back_wages"] += int(_num(r.get("ee_atp_cnt")))
        d["civil_penalties"] += _num(r.get("cmp_assd"))
        if str(r.get("flsa_repeat_violator") or "").upper().startswith("R"):
            d["repeat_violator_cases"] += 1
        y = _year(r.get("findings_start_date"))
        if y:
            d["first_year"] = y if d["first_year"] is None else min(d["first_year"], y)
            d["last_year"] = y if d["last_year"] is None else max(d["last_year"], y)

    scopes = Counter(r["scope"] for r in judged)
    rejected = Counter(
        (r.get("legal_name") or "").strip()
        for r in judged if r["scope"] == "rejected_not_an_operator"
    )
    excluded_line = Counter(
        r.get("naics_code_description") or "?"
        for r in judged if r["scope"] == "excluded_other_line"
    )

    return {
        "source": {
            "url": manifest.get("source_url"),
            "note": manifest.get("source_note"),
            "fetched_at": manifest.get("fetched_at"),
            "candidate_rows": manifest.get("rows"),
            "sha256": manifest.get("sha256"),
        },
        # A standalone sentence, because the console prints it verbatim rather than
        # paraphrasing it. If a venue join is ever added, this string stops being true in the
        # pipeline and on screen in the same edit, which is the only way the two can be
        # relied on not to drift apart.
        "venue_join": (
            "No case here is attached to a venue. WHISARD records an employer establishment "
            "address and never a venue name, so the only thing to join on is ZIP — which put "
            "the 179 geocodable cases across 420 distinct venues."
        ),
        "cases_in_scope": len(kept),
        "back_wages_total": round(sum(_num(r.get("bw_atp_amt")) for r in kept), 2),
        "employees_total": sum(int(_num(r.get("ee_atp_cnt"))) for r in kept),
        "penalties_total": round(sum(_num(r.get("cmp_assd")) for r in kept), 2),
        "by_operator": sorted(
            ({**d, "back_wages": round(d["back_wages"], 2),
              "civil_penalties": round(d["civil_penalties"], 2)} for d in by_op.values()),
            key=lambda d: -d["back_wages"],
        ),
        "scope_counts": dict(sorted(scopes.items())),
        "excluded_other_line_top": [
            {"naics_description": k, "cases": v} for k, v in excluded_line.most_common(10)
        ],
        "rejected_names_top": [
            {"legal_name": k, "cases": v} for k, v in rejected.most_common(10)
        ],
    }


def write(judged: list[dict[str, Any]], prof: dict[str, Any], out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "labor_whd_profile.json").write_text(json.dumps(prof, indent=1) + "\n")

    cols = ["case_id", "operator", "matched_how", "scope", "line_of_business",
            "legal_name", "trade_nm", "naic_cd", "naics_code_description",
            "cty_nm", "st_cd", "zip_cd", "findings_start_date", "findings_end_date",
            "bw_atp_amt", "ee_atp_cnt", "cmp_assd", "case_violtn_cnt",
            "flsa_repeat_violator"]
    with open(out / "labor_whd_cases.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(judged, key=lambda r: (r["scope"], str(r.get("operator")))):
            w.writerow(r)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="re-query the mirror and rewrite the snapshot")
    args = ap.parse_args(argv)

    if args.refresh:
        rows = snapshot()
        print(f"fetched {len(rows)} candidate rows -> {RAW / SNAPSHOT}")

    rows, manifest = load_snapshot()
    judged = [judge(r) for r in rows]
    prof = profile(judged, manifest)
    write(judged, prof)

    s = prof["scope_counts"]
    print(f"WHD candidates {len(rows)} -> in scope {prof['cases_in_scope']}")
    for k in sorted(s):
        print(f"   {k:28} {s[k]}")
    print(f"\n{'operator':26}{'cases':>6}{'back wages':>14}{'workers':>9}  years")
    for d in prof["by_operator"]:
        print(f"   {d['operator']:23}{d['cases']:>6}{d['back_wages']:>14,.0f}"
              f"{d['employees_due_back_wages']:>9,}  {d['first_year']}-{d['last_year']}")
    print(f"\nwrote {OUT / 'labor_whd_profile.json'} and labor_whd_cases.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
