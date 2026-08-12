"""Gate for the WHD labor layer.

Most of this file is about one failure mode: matching a company by name. Three separate
substring traps were found while building this layer, each of which would have printed a
large, confident, wrong number under a real company's name. Every one of them is a test
case below, using the exact string WHD recorded. They are regressions now, not anecdotes.

    .venv/bin/python -m pipeline.labor.check_rules
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from .load import (
    ALIASES,
    DISTINCTIVE,
    OUT,
    RAW,
    clean_name,
    judge,
    line_of_business,
    match_operator,
    profile,
    unknown_operators,
)

PASS: list[str] = []
FAIL: list[str] = []


def want(label: str, ok: bool) -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")


def check_matching() -> None:
    print("\nname matching — the three traps, using WHD's own strings")

    # Trap 1. `%FOODA%` matched 14 supermarkets and a McDonald's, and no real Fooda.
    want("'Foodarama Supermarkets Inc. & Subsidiaries' is not Fooda",
         match_operator("Foodarama Supermarkets Inc. & Subsidiaries", "Shop Rite")[0] is None)
    want("'Legacy Fooda LLC' d/b/a McDonald's is not Fooda",
         match_operator("Legacy Fooda LLC", "McDonald's")[0] is None)
    want("'Fooda, Inc.' still matches Fooda",
         match_operator("Fooda, Inc.", None)[0] == "Fooda")

    # Trap 2. `%SPORT SERVICE%` matched "tranSPORT SERVICES" — 84 ambulance and trucking
    # firms carrying $2,187,898, against a real Delaware North total of $4,648.
    for name in ("Contract Transport Services, Inc.", "A&E Transport Services, Inc.",
                 "Keeney Ambulance & Transport Service, L.L.P.",
                 "Helicopter Transport Services, Inc.",
                 "McNutt Auto Transport Service, Inc."):
        want(f"{name!r} is not Delaware North",
             match_operator(name, None)[0] is None)
    want("'Metroplex SportService, Inc.' still matches Delaware North",
         match_operator("Metroplex SportService, Inc.", None)[0] == "Delaware North")
    want("'Columbus Sport Service, LLC' still matches Delaware North",
         match_operator("Columbus Sport Service, LLC", None)[0] == "Delaware North")

    # Trap 3. Bare "legends" matched 25 local sports bars and zero Legends Hospitality.
    for legal, trade in (("Legends Patio Grill & Bar, Inc.", "Legends Patio Grill & Bar"),
                         ("Rogers Entertainment, LTD", "Legends American Grill"),
                         ("English Stick, Inc.", "Legends Sports Pub & Grill-Green"),
                         ("Legends Smokehouse LLC.", "Legends Smokehouse Restaurant"),
                         ("Let's Golf Daily, Inc.", "Legends Sports Pub & Grill-N Canton")):
        want(f"{trade!r} is not Legends Hospitality",
             match_operator(legal, trade)[0] is None)
    want("'Legends Hospitality LLC' would still match Legends",
         match_operator("Legends Hospitality LLC", None)[0] == "Legends")

    # The same class of error, caught in the same pass.
    want("'Uno Restaurant Associates, Inc.' is not Compass",
         match_operator("Uno Restaurant Associates, Inc.", "Prime Italian Restaurant")[0] is None)
    want("'Morrison's Countryside Buffet, Inc.' is not Compass",
         match_operator("Morrison's Countryside Buffet, Inc.", None)[0] is None)
    want("'Bon Appetit LLC' d/b/a Red Line Diner is not Compass",
         match_operator("Bon Appetit LLC", "Red Line Diner")[0] is None)
    want("'Chef Lalanne, LLC' d/b/a Canteen Bar & Grille is not Compass",
         match_operator("Chef Lalanne, LLC", "Canteen Bar & Grille")[0] is None)
    want("'Restaurant Associates, LLC' still matches Compass",
         match_operator("Restaurant Associates, LLC", "Restaurant Associates")[0] == "Compass")
    want("'Morrison Management Specialists, Inc.' still matches Compass",
         match_operator("Morrison Management Specialists, Inc.", None)[0] == "Compass")

    print("\nname cleaning")
    want("legal suffixes are stripped from the end only",
         clean_name("Aramark Services, Inc.") == "aramark services")
    want("'& Subsidiaries' does not survive",
         clean_name("Foodarama Supermarkets Inc. & Subsidiaries") == "foodarama supermarkets")
    want("a d/b/a is a separator, not a word",
         clean_name("Compass Group USA, Inc. d/b/a Eurest") == "compass group usa eurest")
    want("spelling WHD actually recorded still resolves",
         match_operator("Aramak Uniform And Apparel LLC", None)[0] == "Aramark")

    print("\nthe alias table itself")
    want("every alias resolves to an operator the crosswalk knows",
         not unknown_operators())
    want("no alias is a bare common word that broke this before",
         not ({"legends", "compass", "levy", "morrison", "canteen", "spectra", "metz"}
              & set(ALIASES)))
    want("every distinctive alias is in the alias table",
         DISTINCTIVE <= set(ALIASES))


def check_scope() -> None:
    print("\nline of business")
    want("food service contractors are in scope", line_of_business("722310") == "food_service")
    want("the 5-digit form is in scope too", line_of_business("72231") == "food_service")
    want("uniform supply is adjacent, not food", line_of_business("81233") == "adjacent")
    want("janitorial is adjacent, not food", line_of_business("561720") == "adjacent")
    want("ambulance services are another line entirely",
         line_of_business("621910") == "other_line_of_business")
    want("a missing NAICS is not silently treated as food",
         line_of_business(None) == "other_line_of_business")

    print("\nper-row judgement")
    row = {"legal_name": "Aramark Services, Inc.", "trade_nm": "Aramark",
           "naic_cd": "722310"}
    want("a food-service Aramark case is in scope", judge(row)["scope"] == "in_scope")
    want("an Aramark uniform case is excluded as another line",
         judge({**row, "naic_cd": "81233"})["scope"] == "excluded_other_line")
    want("the offshore/remote arm is excluded the way federal awards excludes it",
         judge({"legal_name": "AraMark U S Offshore and Remote Site, Inc.",
                "trade_nm": None, "naic_cd": "722310"})["scope"] == "excluded_remote_site")
    want("an unmatched name is rejected, not guessed at",
         judge({"legal_name": "Foodarama Supermarkets Inc.", "trade_nm": "Shop Rite",
                "naic_cd": "722310"})["scope"] == "rejected_not_an_operator")


def check_outputs() -> None:
    print("\nemitted files")
    prof_path = OUT / "labor_whd_profile.json"
    csv_path = OUT / "labor_whd_cases.csv"
    snap = RAW / "whd_cases.json"

    if not prof_path.exists() or not csv_path.exists():
        want("the loader has been run", False)
        return

    prof = json.loads(prof_path.read_text())
    rows = list(csv.DictReader(open(csv_path)))
    want("the loader has been run", True)

    want("every candidate row carries a judgement",
         len(rows) == sum(prof["scope_counts"].values()))
    want("the snapshot and the CSV hold the same number of rows",
         (not snap.exists()) or len(json.loads(snap.read_text())) == len(rows))

    kept = [r for r in rows if r["scope"] == "in_scope"]
    want("in-scope count matches the profile", len(kept) == prof["cases_in_scope"])
    want("per-operator cases sum to the total",
         sum(d["cases"] for d in prof["by_operator"]) == prof["cases_in_scope"])
    want("per-operator back wages sum to the total",
         abs(sum(d["back_wages"] for d in prof["by_operator"])
             - prof["back_wages_total"]) < 0.01)
    want("every in-scope row is food service",
         all(r["line_of_business"] == "food_service" for r in kept))
    want("no in-scope row lacks an operator",
         all(r["operator"] for r in kept))

    # The layer's central claim. If a venue_id ever appears here, the ZIP join has been
    # reintroduced and the reason it was rejected has been forgotten.
    want("no case is attached to a venue",
         not any(k.startswith("venue") for k in (rows[0] if rows else {})))
    want("the profile says out loud that there is no venue join",
         "179" in prof.get("venue_join", "") and "420" in prof.get("venue_join", ""))

    want("the mirror is named rather than implied to be dol.gov",
         "labordata.bunkum.us" in (prof["source"]["url"] or "")
         and "dol.gov" in (prof["source"]["note"] or ""))
    want("rejections are reported, not hidden",
         prof["scope_counts"].get("rejected_not_an_operator", 0) > 0
         and len(prof["rejected_names_top"]) > 0)

    print("\nsanity against what was measured by hand")
    by_op = {d["operator"]: d for d in prof["by_operator"]}
    want("Delaware North's total is the food-service one, not the transport one",
         by_op.get("Delaware North", {}).get("back_wages", 0) < 50_000)
    want("Legends carries no cases — every candidate was a sports bar",
         "Legends" not in by_op)
    want("Fooda carries no cases — every candidate was a supermarket",
         "Fooda" not in by_op)
    want("Aramark, Sodexo and Compass all have cases",
         all(o in by_op for o in ("Aramark", "Sodexo", "Compass")))


def check_console() -> None:
    """The two places this data is copied to by hand, and the one place it is retyped.

    `console/public/data/` is a copy, so it can silently be a stale copy. And the layer
    registry's `description` is prose in a TypeScript file: it cannot derive its numbers at
    runtime the way the panel does, so it is the one surface on this layer where a figure is
    typed by a human. That is exactly the thing that goes quietly wrong, so the numbers it
    claims are checked against the profile here rather than trusted.
    """
    print("\nthe console's copy")
    prof_path = OUT / "labor_whd_profile.json"
    console = Path(__file__).resolve().parents[2] / "console"
    copy = console / "public" / "data" / "labor_whd_profile.json"
    registry = console / "src" / "layerRegistry.ts"

    if not prof_path.exists():
        want("the loader has been run", False)
        return

    prof = json.loads(prof_path.read_text())
    want("the console has a copy of the profile", copy.exists())
    if copy.exists():
        want("the console's copy is the one the pipeline emitted",
             copy.read_bytes() == prof_path.read_bytes())

    if not registry.exists():
        want("the layer registry is where it is expected", False)
        return
    text = registry.read_text()

    want("the registry serves the profile the loader writes",
         "'/data/labor_whd_profile.json'" in text)
    want("the venue layer is still declared planned, with its reason",
         "labor_wage_hour_venues" in text and "420" in text)

    # Every figure the registry blurb states, and what it has to equal. If a snapshot is
    # refreshed and the blurb is not, this is what says so.
    rejected = prof["scope_counts"]["rejected_not_an_operator"]
    worst = next(r for r in prof["rejected_names_top"] if r["legal_name"].strip())
    for claim, actual in (
        ("231", prof["cases_in_scope"]),
        ("2,459", f"{prof['employees_total']:,}"),
        ("840", prof["source"]["candidate_rows"]),
        ("493", rejected),
        ("80", worst["cases"]),
    ):
        want(f"the registry's {claim!r} is what the profile says ({actual})",
             claim in text and str(actual) == claim)
    want("the registry's '$2.1M' rounds from the real total",
         "$2.1M" in text and f"${prof['back_wages_total'] / 1e6:.1f}M" == "$2.1M")
    want("the registry names the company behind that 80, not a placeholder",
         worst["legal_name"] in text)


def main() -> int:
    print("WHD labor layer gate")
    check_matching()
    check_scope()
    check_outputs()
    check_console()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} pass")
    if FAIL:
        print("\nfailures:")
        for f in FAIL:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
