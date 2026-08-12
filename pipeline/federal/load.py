"""Read the USAspending exports into federal award records, with scope written on the row.

This is the project's first real data. Everything else about contracts so far has been
synthetic, so the thing this module has to protect against is not a parsing bug — it is
the temptation to make 9,672 federal rows *look like* the venue-concession story the map
tells. They are mostly not that story. 8,909 of them are remote-camp catering; most of the
rest are banquets and refreshments at federal offices, dining halls on Army posts, and
commissaries. Nineteen-ish name a venue in the spine.

So the loader keeps every row and records a judgement on it rather than filtering. An
export that arrives with 9,672 rows and leaves with 393 and no account of the difference
cannot be checked by anyone, including me. `pipeline.federal.check_rules` exists to fail
when the account stops adding up.

Two things are deliberately not loaded, and both are named in the run output rather than
disappearing:

  Assistance awards — 71 rows of PPP loans, SBA disaster loans and loan guarantees. A
    forgiven pandemic loan is not a food-service contract, and the recipient list is
    dominated by companies that merely share a word ("FINANCIAL COMPASS GROUP INC",
    "FLORIDA COMPASS GROUP LLC"). Nothing here is about who feeds a stadium.

  Transactions and subawards — the per-modification rows behind each prime award. Real,
    and worth loading later for the obligation *timeline*, but they multiply the same award
    across many rows, so summing them alongside prime awards would double count.

    .venv/bin/python -m pipeline.federal.load
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from ..extract.candidates import build_index, find_candidates, match_key
from ..schema import (
    FEDERAL_FIELDS,
    FEDERAL_FOOD_NAICS,
    normalize_operator,
    validate_federal,
)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "usaspending"
OUT = ROOT / "output"

# Prime contract awards only — see the module docstring for what the other exports are and
# why summing them together would double count.
CONTRACT_GLOB = "*/Contracts_PrimeAwardSummaries_*.csv"
ASSISTANCE_GLOB = "*/Assistance_PrimeAwardSummaries_*.csv"

# Read straight out of the export. Listed rather than accessed inline so a future download
# with renamed headers fails on the first file with the column name in the message, instead
# of emitting a full run of silent nulls that looks like real missing data.
SOURCE_COLUMNS = [
    "contract_award_unique_key",
    "award_id_piid",
    "recipient_name",
    "awarding_agency_name",
    "awarding_sub_agency_name",
    "naics_code",
    "naics_description",
    "product_or_service_code",
    "product_or_service_code_description",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "award_base_action_date_fiscal_year",
    "total_obligated_amount",
    "current_total_value_of_award",
    "primary_place_of_performance_city_name",
    "primary_place_of_performance_state_code",
    "primary_place_of_performance_zip_4",
    "primary_place_of_performance_country_code",
    "prime_award_base_transaction_description",
]

# venue_id -> {zcta_2010, zcta_2020}, written by the ACS stage. The venue join needs a place
# key the spine can be trusted on, and this is the only one it has: a ZCTA is derived from
# the venue's coordinates rather than copied out of whatever field a source called "city".
VENUE_ZCTA = ROOT / "output" / "venue_zcta.json"
SPINE_FULL = ROOT / "output" / "venues_full.json"

# Kiki's decision, recorded here because it is the single largest thing this module throws
# away and it should not be discoverable only by reading a boolean. Sodexo's remote-sites
# arm files 8,909 awards under NAICS 423990 (durable goods wholesaling) for offshore and
# remote camps. It is catering, but not at a venue, and leaving it in makes Sodexo look
# roughly 400x the size of Aramark purely as an artifact of how the export was filtered.
REMOTE_SITE_RECIPIENTS = {"sodexo remote sites partnership"}


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _text(v: Any) -> Optional[str]:
    return None if _blank(v) else str(v).strip()


def _number(v: Any) -> Optional[float]:
    """Award amounts. Negative is normal — a deobligation gives money back."""
    if _blank(v):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _date(v: Any) -> Optional[str]:
    d = _text(v)
    return d[:10] if d else None


def read_exports(raw: Path = RAW, pattern: str = CONTRACT_GLOB) -> Iterator[dict[str, Any]]:
    """Every prime contract award row, tagged with the file it came from."""
    files = sorted(glob.glob(str(raw / pattern)))
    if not files:
        raise SystemExit(
            f"no USAspending exports under {raw}.\n"
            "  Expected one folder per operator, each holding the CSVs as downloaded."
        )
    for path in files:
        rel = str(Path(path).relative_to(raw))
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in SOURCE_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise SystemExit(
                    f"{rel} is missing expected columns: {missing}\n"
                    "  USAspending changed its export format. Update SOURCE_COLUMNS and\n"
                    "  FEDERAL_FIELDS together rather than reading around the change."
                )
            for row in reader:
                row["__source_file"] = rel
                yield row


def scope(row: dict[str, Any], operator: dict[str, Any]) -> str:
    """Why this row is or is not in scope. First rule that fires wins.

    Order is deliberate. Remote sites are named before anything else so those 8,909 rows
    are logged as `remote_sites` — the decision that was actually made about them — rather
    than as `not_food_service`, which is true of their NAICS but says nothing about why
    they were singled out. Country comes next so the foreign subsidiaries read as foreign
    rather than as a NAICS accident.
    """
    if _norm_name(row["recipient_name"]) in REMOTE_SITE_RECIPIENTS:
        return "remote_sites"
    if _text(row["primary_place_of_performance_country_code"]) != "USA":
        return "foreign_performance"
    if _text(row["naics_code"]) not in FEDERAL_FOOD_NAICS:
        return "not_food_service"
    if operator["relation"] == "unknown":
        return "operator_unresolved"
    return "in_scope"


def _norm_name(s: Any) -> str:
    return str(s or "").strip().lower()


def load_join_keys(
    zcta_path: Path = VENUE_ZCTA, spine_path: Path = SPINE_FULL
) -> dict[str, dict[str, set[str]]]:
    """venue_id -> {"zctas": ..., "aliases": ...}, the two things the join is allowed to use.

    ZCTAS. Both vintages are kept rather than picking one by award date. ZCTA boundaries were
    redrawn between 2010 and 2020, and a postal ZIP on a contract is neither vintage — it is
    a Postal Service delivery route, which is the thing the Census approximates rather than
    the other way round. Requiring the award to name whichever vintage happened to be current
    would reject correct matches over a distinction the award never made.

    ALIASES. Only the names a source actually recorded for the venue, keyed the same way
    `find_candidates` keys its index. Deliberately NOT `match_keys`, which additionally holds
    fragments the spine generated by splitting compound names — see match_venue for what that
    difference cost.
    """
    for p in (zcta_path, spine_path):
        if not p.exists():
            raise SystemExit(
                f"{p} is missing — the venue join needs it.\n"
                "  Run the spine and ACS stages before the federal loader."
            )
    zctas = json.loads(zcta_path.read_text())
    keys: dict[str, dict[str, set[str]]] = {}
    for v in json.loads(spine_path.read_text()):
        z = zctas.get(v["venue_id"]) or {}
        keys[v["venue_id"]] = {
            "zctas": {x for x in (z.get("zcta_2010"), z.get("zcta_2020")) if x},
            "aliases": {match_key(a["name"]) for a in v.get("aliases") or []},
        }
    return keys


def _zip5(v: Any) -> Optional[str]:
    """The 5-digit ZIP out of USAspending's ZIP+4. 218 of 9,672 rows carry none."""
    z = (_text(v) or "")[:5]
    return z if len(z) == 5 and z.isdigit() else None


def match_venue(
    row: dict[str, Any], index: dict[str, Any], keys: dict[str, dict[str, set[str]]]
) -> tuple[Optional[str], str]:
    """Tie an award to a spine venue, or decline to.

    Three gates — the description names the venue, the ZIP agrees, and the name it was
    matched on is one a source actually recorded. Together they match 8 awards at 3 venues.
    Each was sabotage-tested over the 393 in-scope awards to check it is not decorative:

        drop the name gate    ZIP alone matches   133 awards at 136 venues
        drop the place gate   name alone matches   26 awards at  13 venues
        drop the alias gate                        11 awards at   4 venues, $53.2M

    None of those is a join. They are the three ways of being wrong that the other gates
    exist to catch, and the third one is the expensive one — see ALIAS below.

    NAME. A name hit alone is not enough, and that is not caution — it was measured. Matching
    on the description alone produced twelve hits, of which ten were wrong:

        "JOINT TASK FORCE"                 -> The Joint, a Nevada music venue
        "FOSTERING SAFE, WELCOME ..."      -> T-Mobile Park, via a former name
        "FOREIGN AFFAIRS TRAINING CENTER"  -> Bon Secours Training Center, Richmond
        "30TH INTERNATIONAL COLLOQUIUM"    -> The International Golf Club
        "... AT USCG ACADEMY, NEW LONDON"  -> the Military Academy at West Point

    The cause is specific rather than general bad luck. `find_candidates` protects venue
    names that are also ordinary words — Pond, Joint, Safe — by requiring the word to appear
    capitalized, the way a newspaper prints a proper noun. USAspending descriptions are
    written entirely in capitals, so that guard passes on every token and every common-word
    venue in the spine becomes reachable.

    PLACE. This used to compare the award's city against the spine's `city`, and that field
    cannot carry the comparison: 35.9% of venues hold their own state's name in it, and the
    Coast Guard Academy's city is literally "Connecticut". So the place check was throwing
    away correct matches on the strength of a corrupt string. Moving it to ZIP-against-ZCTA
    is what recovers them, and every surviving match was read individually:

        3x  Walter E. Washington Convention Center   ZIP 20001 = ZCTA 20001
        3x  US Merchant Marine Academy               pop "GREAT NECK" 11024, spine city
                                                     "Kings Point" — postal vs municipal name
        2x  US Coast Guard Academy                   pop "NEW LONDON" 06320, spine city
                                                     "Connecticut" — the contamination itself

    ZIP is also the *stricter* rule where it matters. A state-only place check finds more
    awards, and the two it adds are both wrong: a New York City architecture reception and a
    Great Neck order that belongs to the Merchant Marine Academy, each matched to West Point
    on the word "Academy". ZIP rejects both. There is deliberately no state clause alongside
    it — a ZIP determines its state, so a state check would only re-decide something already
    settled while excluding the 1,085 spine venues that carry no state at all.

    ALIAS. The matched name has to be one a source recorded, not a fragment the spine
    generated. `match_keys` deliberately holds sub-phrases so that newspaper prose has
    something to hit, and for prose that is right; for attributing a dollar figure it is too
    loose, because a fragment of a compound name can name a different and much larger thing.
    Without this gate the join takes in a $53.0M Sodexo award reading "NUTRITION CARE SERVICES
    AT WEST POINT, NY FORT STEWART, GA FORT LEONARD WOOD, MO FORT RILEY, KS FORT IRWIN, CA
    ...". Its place of performance genuinely is ZIP 65473, and the spine genuinely has a venue
    there — but the venue is "Marine Corps Detachment, Fort Leonard Wood" and the key that
    fired is `fort leonard wood`, the post it sits on. One obligation, six Army posts, landing
    whole on one dot, and 99.7% of the map's federal total. The gate is not free: it also
    drops a correct $45,674 convention-centre award whose description said "THE WASHINGTON
    CONVENTION CENTER" rather than the full "Walter E. Washington Convention Center". Losing
    $45,674 of real attribution to refuse $53.0M of false attribution is the trade, and it was
    made deliberately.

    Declining is the expected outcome. 358 of the 393 in-scope awards name no venue at all —
    they read "MEALS", "FOOD SERVICES", "PICNIC LUNCH PROVIDED TO EMPLOYEES" — and a spine of
    stadiums and arenas should not match a dining facility at Fort Bragg. A loose substring
    sweep of 11,688 distinctive venue names over all 381 unmatched descriptions turned up 2
    candidates, one of them probably a different building. There is no large missed join here.
    """
    text = _text(row["prime_award_base_transaction_description"])
    if not text:
        return None, "unmatched"

    zip5 = _zip5(row["primary_place_of_performance_zip_4"])
    if not zip5:
        return None, "unmatched"

    for c in find_candidates(text, index):
        k = keys.get(c["venue_id"])
        if k and zip5 in k["zctas"] and c["matched_as"] in k["aliases"]:
            return c["venue_id"], "name_and_zip"
    return None, "unmatched"


def to_record(
    row: dict[str, Any], index: dict[str, Any], keys: dict[str, dict[str, set[str]]]
) -> dict[str, Any]:
    operator = normalize_operator(row["recipient_name"])
    reason = scope(row, operator)
    in_scope = reason == "in_scope"

    # Only in-scope rows are matched. An excluded row with a venue_id is a dot on the map
    # for work the scope rule already ruled out, so the join is never even attempted.
    venue_id, venue_match = match_venue(row, index, keys) if in_scope else (None, "unmatched")

    return {
        "award_id": _text(row["contract_award_unique_key"]),
        "piid": _text(row["award_id_piid"]),
        "operator_raw": _text(row["recipient_name"]),
        "operator_normalized": operator["operator_normalized"] if in_scope else None,
        "sub_brand": operator.get("sub_brand"),
        "operator_relation": operator["relation"],
        "awarding_agency": _text(row["awarding_agency_name"]),
        "awarding_sub_agency": _text(row["awarding_sub_agency_name"]),
        "naics_code": _text(row["naics_code"]),
        "naics_description": _text(row["naics_description"]),
        "psc_code": _text(row["product_or_service_code"]),
        "psc_description": _text(row["product_or_service_code_description"]),
        "start_date": _date(row["period_of_performance_start_date"]),
        "end_date": _date(row["period_of_performance_current_end_date"]),
        "fiscal_year": _number(row["award_base_action_date_fiscal_year"]),
        "obligated_amount": _number(row["total_obligated_amount"]),
        "current_value": _number(row["current_total_value_of_award"]),
        "pop_city": _text(row["primary_place_of_performance_city_name"]),
        "pop_state": _text(row["primary_place_of_performance_state_code"]),
        "pop_zip": _zip5(row["primary_place_of_performance_zip_4"]),
        "pop_country": _text(row["primary_place_of_performance_country_code"]),
        "description": _text(row["prime_award_base_transaction_description"]),
        "venue_id": venue_id,
        "venue_match": venue_match,
        "in_scope": in_scope,
        "scope_reason": reason,
        "source_file": row["__source_file"],
    }


def load(raw: Path = RAW) -> dict[str, Any]:
    """All prime contract awards as federal records, plus the counts that explain them."""
    index = build_index()
    keys = load_join_keys()

    records: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: dict[str, str] = {}
    duplicates = 0

    for row in read_exports(raw):
        rec = to_record(row, index, keys)

        # The four exports were downloaded per operator, and a joint venture or a parent
        # search can land the same award in two of them. Deduplicating on the award key is
        # what keeps "total obligated" from counting one contract twice.
        key = rec["award_id"]
        if key in seen:
            duplicates += 1
            continue
        seen[key] = rec["source_file"]

        problems += validate_federal(rec)
        records.append(rec)

    kept = [r for r in records if r["in_scope"]]
    by_reason: dict[str, int] = {}
    for r in records:
        by_reason[r["scope_reason"]] = by_reason.get(r["scope_reason"], 0) + 1
    by_match: dict[str, int] = {}
    for r in kept:
        by_match[r["venue_match"]] = by_match.get(r["venue_match"], 0) + 1

    return {
        "records": records,
        "problems": problems,
        "stats": {
            "rows_read": len(records) + duplicates,
            "duplicates_dropped": duplicates,
            "records": len(records),
            "in_scope": len(kept),
            "venue_matched": sum(1 for r in kept if r["venue_id"]),
            "by_reason": by_reason,
            "by_match": by_match,
            "assistance_rows_not_loaded": _count(RAW, ASSISTANCE_GLOB),
        },
    }


def _count(raw: Path, pattern: str) -> int:
    total = 0
    for path in glob.glob(str(raw / pattern)):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            total += sum(1 for _ in csv.DictReader(fh))
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--write", action="store_true", help="write federal_awards.json")
    ap.add_argument("--show-matched", action="store_true",
                    help="print every award that tied to a spine venue")
    args = ap.parse_args()

    result = load(args.raw)
    s = result["stats"]

    print(f"\nLOAD {args.raw}")
    print(f"  rows read           {s['rows_read']}")
    print(f"  duplicate awards    {s['duplicates_dropped']}")
    print(f"  records             {s['records']}")
    print(f"  in scope            {s['in_scope']}")
    print(f"  tied to a venue     {s['venue_matched']}")
    print("\n  scope:")
    for reason, n in sorted(s["by_reason"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:>6}  {reason}")
    print("\n  venue join (in-scope rows only):")
    for how, n in sorted(s["by_match"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:>6}  {how}")
    print(f"\n  assistance rows not loaded: {s['assistance_rows_not_loaded']}"
          " (PPP and SBA loans — see module docstring)")

    if args.show_matched:
        print("\n  awards tied to a spine venue:")
        for r in result["records"]:
            if r["venue_id"]:
                amt = r["obligated_amount"] or 0
                print(f"    {r['venue_id']:<14} {str(r['operator_normalized']):<12} "
                      f"{r['fiscal_year'] and int(r['fiscal_year'])}  ${amt:>12,.0f}  "
                      f"[{r['venue_match']}] {(r['description'] or '')[:60]}")

    if result["problems"]:
        print(f"\n  SCHEMA PROBLEMS ({len(result['problems'])}):")
        for p in result["problems"][:20]:
            print(f"    {p}")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "federal_awards.json"
        path.write_text(json.dumps(result["records"], indent=2))
        print(f"\n  wrote {path.relative_to(ROOT.parent)} ({len(result['records'])} records)")

    sys.exit(1 if result["problems"] else 0)


if __name__ == "__main__":
    main()
