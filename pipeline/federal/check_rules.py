"""Gate for the federal loader — do the scope rules still do what they say?

Two halves, because either one alone is a gate that cannot fail.

The RULE CHECKS run each scope rule against a hand-written award that should trip it, and
against one that should not. They would pass on an empty dataset, which is exactly why they
are not enough on their own: they prove the rules are implemented, not that they were
applied.

The INVARIANTS run over the real 9,672-row export and check the things that must hold no
matter what the data says — that the scope reasons account for every row, that nothing
excluded kept a venue_id, that every in-scope row really does satisfy every rule it claims
to have passed. These cannot pass on an empty dataset, because they also assert the export
is there and non-trivial.

The invariant that matters most is the accounting one. This module's whole claim to the
reader is "393 of 9,672, and here are the other 9,279" — and a claim like that is worth
exactly as much as the check that it adds up.

    .venv/bin/python -m pipeline.federal.check_rules
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from ..extract.candidates import build_index, find_candidates
from ..schema import FEDERAL_FOOD_NAICS, normalize_operator, validate_federal
from .load import RAW, load, load_join_keys, scope, to_record

ROOT = Path(__file__).resolve().parent.parent
SPINE_IN = ROOT / "output" / "venues_full.json"


def award(**over: Any) -> dict[str, Any]:
    """A US food-service award that passes every rule, so a test can break exactly one."""
    row = {
        "contract_award_unique_key": "CONT_AWD_TEST",
        "award_id_piid": "TEST0001",
        "recipient_name": "ARAMARK SERVICES, INC.",
        "awarding_agency_name": "Department of Defense",
        "awarding_sub_agency_name": "Department of the Navy",
        "naics_code": "722310",
        "naics_description": "FOOD SERVICE CONTRACTORS",
        "product_or_service_code": "S203",
        "product_or_service_code_description": "FOOD SERVICES",
        "period_of_performance_start_date": "2015-01-01",
        "period_of_performance_current_end_date": "2018-12-31",
        "award_base_action_date_fiscal_year": "2015",
        "total_obligated_amount": "1000.00",
        "current_total_value_of_award": "1000.00",
        "primary_place_of_performance_city_name": "DENVER",
        "primary_place_of_performance_state_code": "CO",
        "primary_place_of_performance_zip_4": "802021234",
        "primary_place_of_performance_country_code": "USA",
        "prime_award_base_transaction_description": "FOOD SERVICE",
        "__source_file": "test/Contracts_PrimeAwardSummaries.csv",
    }
    row.update(over)
    return row


# (label, row, expected scope_reason)
RULE_CHECKS: list[tuple[str, dict[str, Any], str]] = [
    ("a US food-service award by a known operator is kept",
     award(), "in_scope"),
    ("remote sites are excluded by name, not left to their NAICS",
     award(recipient_name="SODEXO REMOTE SITES PARTNERSHIP", naics_code="423990"),
     "remote_sites"),
    ("remote sites are named even when the NAICS would have kept them",
     award(recipient_name="SODEXO REMOTE SITES PARTNERSHIP", naics_code="722310"),
     "remote_sites"),
    ("work performed abroad is out of scope",
     award(recipient_name="COMPASS GROUP ITALIA S.P.A.",
           primary_place_of_performance_country_code="ITA"),
     "foreign_performance"),
    ("a UK subsidiary is foreign even though its name resolves",
     award(recipient_name="SODEXO LTD", primary_place_of_performance_country_code="GBR"),
     "foreign_performance"),
    ("janitorial work is not food service",
     award(recipient_name="SODEXO LTD", naics_code="561720"), "not_food_service"),
    ("facilities support is not food service either",
     award(naics_code="561210"), "not_food_service"),
    ("durable goods wholesaling is not food service",
     award(recipient_name="SODEXO MANAGEMENT INC.", naics_code="423990"),
     "not_food_service"),
    ("a blank NAICS is not quietly treated as food service",
     award(naics_code=""), "not_food_service"),
    ("a company that merely shares a word is not an operator",
     award(recipient_name="BROKEN COMPASS GROUP LLC"), "operator_unresolved"),
    ("the PR agency called The Compass Group is not Compass",
     award(recipient_name="THE COMPASS GROUP INC"), "operator_unresolved"),
    ("caterers count as food service",
     award(naics_code="722320"), "in_scope"),
    ("community food services count",
     award(recipient_name="COMPASS GROUP USA INC", naics_code="624210"), "in_scope"),
]

# (label, check over the real loaded result)
INVARIANTS: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []


def invariant(label: str) -> Callable[[Callable[[dict[str, Any]], bool]], Any]:
    def register(fn: Callable[[dict[str, Any]], bool]) -> Callable[[dict[str, Any]], bool]:
        INVARIANTS.append((label, fn))
        return fn
    return register


@invariant("the export is actually there and non-trivial")
def _loaded(r: dict[str, Any]) -> bool:
    return len(r["records"]) > 1000


@invariant("every row validates against FEDERAL_FIELDS")
def _valid(r: dict[str, Any]) -> bool:
    return not r["problems"]


@invariant("scope reasons account for every row, with none left over")
def _accounting(r: dict[str, Any]) -> bool:
    return sum(r["stats"]["by_reason"].values()) == len(r["records"])


@invariant("award_id is unique, so no contract is counted twice")
def _unique(r: dict[str, Any]) -> bool:
    ids = [x["award_id"] for x in r["records"]]
    return len(ids) == len(set(ids))


@invariant("no in-scope row performs work outside the US")
def _domestic(r: dict[str, Any]) -> bool:
    return all(x["pop_country"] == "USA" for x in r["records"] if x["in_scope"])


@invariant("no in-scope row carries a non-food NAICS")
def _food(r: dict[str, Any]) -> bool:
    return all(x["naics_code"] in FEDERAL_FOOD_NAICS for x in r["records"] if x["in_scope"])


@invariant("no in-scope row has an unresolved operator")
def _resolved(r: dict[str, Any]) -> bool:
    return all(x["operator_relation"] != "unknown" for x in r["records"] if x["in_scope"])


@invariant("remote sites never survive into scope")
def _remote(r: dict[str, Any]) -> bool:
    return not any(
        "REMOTE SITES" in (x["operator_raw"] or "") for x in r["records"] if x["in_scope"]
    )


@invariant("no excluded row kept a venue_id")
def _no_ghost_venues(r: dict[str, Any]) -> bool:
    return not any(x["venue_id"] for x in r["records"] if not x["in_scope"])


@invariant("every matched venue_id exists in the spine")
def _venues_exist(r: dict[str, Any]) -> bool:
    if not SPINE_IN.exists():
        return False
    spine = {v["venue_id"] for v in json.loads(SPINE_IN.read_text())}
    return all(x["venue_id"] in spine for x in r["records"] if x["venue_id"])


@invariant("every match agrees with the place of performance that produced it")
def _place_agrees(r: dict[str, Any]) -> bool:
    # Deliberately not a city check any more. The spine's `city` is contaminated — 35.9% of
    # venues hold their own state's name in it — so asserting on it would fail the correct
    # matches and pass nothing extra. The ZCTA is derived from the venue's coordinates.
    keys = load_join_keys()
    for x in r["records"]:
        if not x["venue_id"]:
            continue
        if x["pop_zip"] not in keys.get(x["venue_id"], {}).get("zctas", set()):
            return False
    return True


@invariant("no match rests on a name fragment the spine generated rather than recorded")
def _named_by_a_source(r: dict[str, Any]) -> bool:
    # The gate that keeps a $53.0M six-post Army contract off one dot, by refusing the key
    # `fort leonard wood` as a name for "Marine Corps Detachment, Fort Leonard Wood". It has
    # to be asserted here and not only inside match_venue, because the failure it prevents is
    # a plausible-looking match rather than an error — nothing else would notice.
    keys = load_join_keys()
    index = build_index()
    for x in r["records"]:
        if not x["venue_id"]:
            continue
        aliases = keys.get(x["venue_id"], {}).get("aliases", set())
        hit = next(
            (c for c in find_candidates(x["description"] or "", index)
             if c["venue_id"] == x["venue_id"]),
            None,
        )
        if hit is None or hit["matched_as"] not in aliases:
            return False
    return True


@invariant("venue_match and venue_id never disagree")
def _match_consistent(r: dict[str, Any]) -> bool:
    return all(
        (x["venue_match"] != "unmatched") == bool(x["venue_id"]) for x in r["records"]
    )


@invariant("the operator crosswalk still resolves every kept recipient name")
def _crosswalk(r: dict[str, Any]) -> bool:
    # Guards the direction of travel: the crosswalk was extended for this data, so a later
    # edit that drops one of those entries has to fail here rather than silently move
    # hundreds of awards into operator_unresolved.
    names = {x["operator_raw"] for x in r["records"] if x["in_scope"]}
    return all(normalize_operator(n)["relation"] != "unknown" for n in names)


def main() -> int:
    rule_failures: list[str] = []
    invariant_failures: list[str] = []

    # An empty index: the rule checks are about scope, and giving them a real spine would
    # make them depend on whether some test city happens to hold a venue.
    index: dict[str, Any] = {"key_to_venues": {}, "trigger_to_keys": {}, "cased_keys": set()}
    for label, row, expected in RULE_CHECKS:
        actual = scope(row, normalize_operator(row["recipient_name"]))
        if actual != expected:
            rule_failures.append(f"{label}\n      expected {expected!r}, got {actual!r}")
            continue
        # The record built from it must agree with the rule that judged it.
        problems = validate_federal(to_record(row, index, {}))
        if problems:
            rule_failures.append(f"{label}: record does not validate — {problems}")

    result = load(RAW)
    for label, check in INVARIANTS:
        try:
            ok = check(result)
        except Exception as exc:                                    # noqa: BLE001
            invariant_failures.append(f"{label}: raised {exc!r}")
            continue
        if not ok:
            invariant_failures.append(label)

    s = result["stats"]
    print(f"federal scope rules : "
          f"{len(RULE_CHECKS) - len(rule_failures)}/{len(RULE_CHECKS)} pass")
    print(f"invariants          : "
          f"{len(INVARIANTS) - len(invariant_failures)}/{len(INVARIANTS)} pass")
    print(f"rows checked        : {len(result['records'])}"
          f"  ({s['in_scope']} in scope, {s['venue_matched']} tied to a venue)")

    for f in rule_failures + invariant_failures:
        print(f"  FAIL  {f}")

    if rule_failures or invariant_failures:
        return 1
    print(f"\nPASS — {len(RULE_CHECKS) + len(INVARIANTS)} checks over "
          f"{len(result['records'])} real award rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
