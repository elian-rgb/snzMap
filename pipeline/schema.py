"""Locked record schemas — build order step 2.

Three record types, per the plan's data contract:

  A. contract event  — what ONE article yields (extraction target)
  B. tenure record   — one operator's run at one venue (THE deliverable)
  C. hunt log entry  — one search that was performed, including the ones that found nothing

Everything downstream (the extraction prompt's JSON schema, the span pairer, the eval
gate, the CSV emitters) reads its field list from here, so the schema is changed in one
place or not at all.

Two reconciliations this module makes explicit, because they are the parts that would
otherwise drift:

  1. **Kiki's workbook is the human-facing form of the tenure record, and it does not
     change.** Her README says "don't add new columns ad hoc — schema changes are
     deliberate promotions." So the pipeline never writes new columns into the workbook.
     Machine keys the pipeline needs (`tenure_id`, `venue_id`, `operator_normalized`,
     `derived_from`) are DERIVED on load, not stored in her file. `WORKBOOK_TENURE_COLUMNS`
     below is a literal copy of her header row and is what round-trips.

  2. **Two venue vocabularies exist on purpose.** The spine types Coors Field as
     `ballpark`; the workbook dropdown types it `stadium`. The spine's vocabulary is
     finer (it has to classify 7.5k venues); the workbook's includes institution kinds the
     spine deliberately does not enumerate (`university`, `hospital`, `school_district`,
     `corporate` — the plan calls that set unbounded). Neither is wrong. `venue_id` is the
     join, `SPINE_TO_TENURE_TYPE` is the projection, and no code should compare the two
     type strings directly.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional, Tuple

# ── Controlled vocabularies ────────────────────────────────────────────────────

EVENT_TYPES = [
    "won", "lost", "renewed", "expired", "self_op", "strike", "violation", "initiative",
]

DATE_PRECISIONS = ["exact", "month", "year", "approx"]

# Never blank. `ongoing` (they still hold it) and `unknown` (we have not found the end yet)
# are analytically opposite; collapsing them destroys the distinction the project exists on.
END_STATUSES = ["ongoing", "ended", "unknown"]

EXIT_MODES = [
    "lost_bid",
    "self_op_conversion",   # institution took food service back in-house
    "terminated",           # for cause
    "venue_closed",
    "merger_or_acquisition",
    "other",
    "unknown",
]

HUNT_RESULTS = ["found_events", "partial_info", "nothing_found"]

# ── Federal awards vocabulary ──────────────────────────────────────────────────
#
# USAspending is a *different kind of source* from an article, and the record type keeps
# that separation. An article says "Aramark won the Coors Field concession"; a federal
# award says "the Navy obligated $2.1M to Aramark Services, Inc. under NAICS 722310".
# The second is a spending fact about an operator, not a tenure claim about a venue, and
# only a small minority of them name a venue at all.
#
# Every row is kept. `in_scope` is a judgement recorded on the row, never a reason to drop
# it — an export that silently loses 92% of its rows is unauditable, and the excluded rows
# are the evidence that the scope rule did what it says.

# Why a row is out of scope. One reason per row, first rule that fires.
FEDERAL_EXCLUSIONS = [
    "in_scope",
    "not_food_service",     # NAICS is not food service / catering
    "foreign_performance",  # work performed outside the US
    "remote_sites",         # offshore and remote-camp catering, not a venue
    "operator_unresolved",  # recipient name does not resolve to a known operator
]

# NAICS codes that count as food service. Narrow on purpose: a facilities-support or
# janitorial award at a hospital is real work, but it is not the concession business this
# project is about, and counting it would make "operator revenue" mean two things at once.
FEDERAL_FOOD_NAICS = {
    "722310",  # food service contractors
    "722320",  # caterers
    "624210",  # community food services
    "722511",  # full-service restaurants
    "722513",  # limited-service restaurants
    "445110",  # supermarkets / other grocery
}

# How a federal award was tied to a spine venue. Only two values, because matching on the
# description alone was tried and measured: ten of its twelve hits were wrong, for the
# reason documented in pipeline.federal.load.match_venue. There is no weaker tier to fall
# back to, so there is no name to record for one.
#
# The place half of `name_and_zip` used to be the venue's city, and was renamed when it
# changed to the ZIP, so a stale `federal_awards.json` fails validation instead of being
# read as if it had been produced by the current rule.
#
# `unmatched` is the common case and is not a failure — most federal food service happens
# at military posts, VA hospitals and embassies, none of which are in a spine built from
# stadiums and arenas.
FEDERAL_VENUE_MATCH = ["unmatched", "name_and_zip"]

# ── ACS context vocabulary ─────────────────────────────────────────────────────
#
# A fifth record type, and the weakest claim in the project. A contract event says something
# about a venue; an ACS row says something about the *neighbourhood a venue sits in*, which
# is a fact about a ZIP Code Tabulation Area that a venue happens to fall inside. ZCTAs are
# large and heterogeneous — a downtown arena's ZCTA contains offices and apartments that have
# nothing to do with the arena — so this is context for reading a venue, never evidence about
# it. The record type keeps that separation visible rather than flattening ACS columns onto
# the venue.

# How a venue was tied to a ZCTA. The vintage split is not a technicality: the ACS exports on
# disk change tabulation geography between the 2020 and 2021 five-year releases (33,120 ZCTA
# rows through 2020, 33,774 from 2021), and 2020-Census ZCTAs reuse five-digit codes that no
# longer mean the same polygon. A venue therefore carries one ZCTA per era.
ACS_ZCTA_MATCH = [
    "both_vintages",  # usable across the whole 2011-2024 series
    "2010_only",      # context available for ACS 5Y 2011-2020 only
    "2020_only",      # context available for ACS 5Y 2021-2024 only
    "no_zcta",        # coordinate falls outside every ZCTA — water, pier, unaddressed land
]

# The last ACS 5-year vintage tabulated on 2010-Census ZCTAs. Vintages after this one use
# the 2020-Census ZCTAs, so `zcta_2010` answers for years <= this and `zcta_2020` after it.
ACS_LAST_2010_VINTAGE = 2020

# Median household income is published in the dollars *of its own vintage year* — the 2011
# file says "in 2011 inflation-adjusted dollars", the 2024 file says 2024. Nothing here
# deflates it, so the field name carries the warning rather than relying on a footnote.
ACS_MEASURES = [
    "workers_total",            # B08006_001E — denominator for both shares below
    "median_household_income",  # B19013_001E — NOMINAL, in each vintage's own dollars
    "transit_share",            # B08006_008E / B08006_001E
    "long_commute_share",       # (B08303_011E + _012E + _013E) / B08303_001E, 45+ minutes
]

# The workbook dropdown, verbatim.
TENURE_VENUE_TYPES = [
    "stadium", "arena", "university", "hospital", "school_district",
    "museum", "convention_center", "corporate", "other",
]

# Spine vocabulary -> workbook vocabulary. Only used to pre-fill; a human may override.
SPINE_TO_TENURE_TYPE = {
    "stadium": "stadium",
    "ballpark": "stadium",
    "arena": "arena",
    "convention_center": "convention_center",
    "racetrack": "other",
    "amphitheater": "other",
    "golf_course": "other",
    "aquatic_center": "other",
    "ski_resort": "other",
    "recreation": "other",
    "other": "other",
}

# ── Operator crosswalk ─────────────────────────────────────────────────────────
#
# Three relations, kept separate because conflating them rewrites history:
#
#   rename     — same company, new name. Safe to normalize in both directions
#                (ARA Services IS Aramark; a 1991 ARA contract is an Aramark run).
#   sub_brand  — an operating division. Normalize to the parent, keep the division,
#                because "Levy at the United Center" and "Compass at the United Center"
#                are the same contract described at two levels.
#   acquired   — a company that was later bought. NEVER normalized to the acquirer:
#                a 2005 Centerplate contract was not a Sodexo contract, and folding it in
#                would invent a Sodexo run that no article reports. The acquisition year is
#                recorded only so the span logic can FLAG a boundary, never to close a span.

RENAMES = {
    "ara": "Aramark",
    "ara services": "Aramark",
    "aramark corporation": "Aramark",
    "sodexho": "Sodexo",
    "sodexho inc": "Sodexo",
    "sodexho marriott": "Sodexo",
    "sodexho marriott services": "Sodexo",
    "marriott management services": "Sodexo",
    "compass group": "Compass",
    "compass group north america": "Compass",
    "compass group usa": "Compass",
    "delaware north companies": "Delaware North",

    # Legal entity names, as they appear in federal award registries. A newspaper prints
    # "Aramark"; USAspending prints the entity that signed. Same company either way.
    # Each of these was confirmed against the NAICS on its own awards — every one files
    # under 722310 (food service contractors) or 722320 (caterers).
    #
    # Deliberately absent, and each for a different reason:
    #   THE COMPASS GROUP INC           — a different company. Its awards are NAICS 561499
    #                                     and 541820, business support and public relations.
    #                                     A name-only match here would have invented Compass
    #                                     revenue out of a PR agency.
    #   COMPASS GROUP ITALIA S.P.A.     — a foreign subsidiary performing abroad. Scope is
    #                                     US place-of-performance, so it is filtered out
    #                                     upstream; mapping it here would let non-US work
    #                                     land on a US map if that filter ever slipped.
    #   SODEXO REMOTE SITES PARTNERSHIP — offshore/remote camp catering, filed under durable
    #                                     goods wholesaling, not food service at a venue.
    #                                     Excluded by rule and logged; leaving it unmapped
    #                                     means a missed exclusion surfaces as needs_review
    #                                     instead of silently making Sodexo look 400x larger
    #                                     than Aramark.
    #   ROTH BROS INC, SODEXO CTM LLC   — real Sodexo entities, but engineering and
    #                                     electronics repair. Out of scope by NAICS, so
    #                                     mapping the name would only smuggle them past it.
    "aramark services": "Aramark",
    "sodexo management": "Sodexo",
    "sodexo operations": "Sodexo",
    "sodexo federal services": "Sodexo",
    "sodexo america": "Sodexo",
}

SUB_BRANDS = {
    # Compass
    "chartwells": "Compass", "flik": "Compass", "flik international": "Compass",
    "levy": "Compass", "levy restaurants": "Compass",
    "canteen": "Compass", "canteen services": "Compass",
    "bon appetit": "Compass", "bon appétit": "Compass",
    "bon appetit management": "Compass", "bon appétit management": "Compass",
    "eurest": "Compass", "eurest dining services": "Compass",
    "morrison": "Compass", "morrison healthcare": "Compass",
    "restaurant associates": "Compass",
    "wolfgang puck catering": "Compass",
    # Aramark
    "aramark sports and entertainment": "Aramark",
    "aramark sports & entertainment": "Aramark",
    "aramark refreshment services": "Aramark",
    "aramark educational services": "Aramark",
    # Sodexo
    "sodexo live": "Sodexo", "sodexo live!": "Sodexo",
    # A Sodexo / Magic Johnson Enterprises joint venture, and it bids federal food service
    # under its own name. Sodexo is the operating parent, so it normalizes there, but the
    # JV name is kept as the sub_brand because the partnership is the point of it.
    "sodexomagic": "Sodexo",
    # Delaware North
    "sportservice": "Delaware North",
    "delaware north sportservice": "Delaware North",
    # Oak View Group
    "ovg hospitality": "Oak View Group",
    "spectra food services": "Oak View Group",
    "spectra food services and hospitality": "Oak View Group",
}

# acquired company -> (acquirer, year, confidence)
# `confidence` is honest, not decorative: "low" years must be confirmed by Kiki before any
# analysis leans on them. Nothing in this module uses the year to change data — only to set
# needs_review when a span crosses it.
ACQUISITIONS = {
    "centerplate": ("Sodexo", 2017, "high"),
    "volume services america": ("Centerplate", 2004, "low"),
    # The federal registry's form of the same company. Still `acquired`, not a rename:
    # a 2001 Volume Services award was not a Centerplate award.
    "volume services": ("Centerplate", 2004, "low"),
    "ogden entertainment": ("Aramark", 2000, "medium"),
    "harry m. stevens": ("Aramark", 1994, "medium"),
    "harry m stevens": ("Aramark", 1994, "medium"),
    "spectra": ("Oak View Group", 2021, "high"),
    "ovations food services": ("Spectra", 2016, "low"),
    "guckenheimer": ("ISS", 2016, "low"),
}

# Operators that stand on their own — listed so an unrecognized name is visibly
# unrecognized rather than quietly passed through as if it were canonical.
KNOWN_OPERATORS = {
    "Aramark", "Sodexo", "Compass", "Delaware North", "Legends", "Oak View Group",
    "Centerplate", "Spectra", "Levy", "Metz Culinary Management", "Thompson Hospitality",
    "Whitsons Culinary Group", "Fooda", "Self-operated",
}

SELF_OP_FORMS = {
    "self-op", "self op", "self-operated", "self operated", "in-house", "in house",
    "none", "n/a",
}


def _norm(s: str) -> str:
    # Fold accents first. Without this the final character strip turns "é" into a space,
    # so "Bon Appétit" normalized to "bon app tit" and never matched its own crosswalk
    # entry — while the unaccented spelling did. The company writes itself with the accent.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip().rstrip(".")
    # `ltd|plc|lp|llp` are here for federal registry names. USAspending prints the legal
    # entity ("SODEXO LTD", "COMPASS GROUP PLC"), not the name a newspaper would print,
    # and a legal suffix is not a different company.
    s = re.sub(
        r"\b(inc|incorporated|llc|corp|corporation|co|company|group"
        r"|usa|north america|ltd|plc|lp|llp)\b",
        " ",
        s,
    )
    s = re.sub(r"[^a-z0-9&! ]+", " ", s)
    # Collapse runs of spaces. Every step above replaces with a space rather than deleting,
    # so "Harry M. Stevens" came out "harry m  stevens" and missed the "harry m stevens"
    # key by one character. Crosswalk keys are written the way a person would write them.
    return re.sub(r" {2,}", " ", s).strip()


_SELF_OP_KEYS = {_norm(f) for f in SELF_OP_FORMS}


def normalize_operator(raw: str | None) -> dict[str, Any]:
    """Resolve an operator name as printed into (parent, sub_brand, how we know).

    Returns `relation` so callers can tell a safe rename from a merger boundary:
      exact | rename | sub_brand | acquired | self_op | unknown
    """
    if not raw or not str(raw).strip():
        return {"raw": raw, "operator_normalized": None, "sub_brand": None,
                "relation": "unknown", "needs_review": True}

    raw = str(raw).strip()
    key = _norm(raw)

    # Compared against normalized forms, not the literal set: `_norm` turns "n/a" into
    # "n a", so the raw set never matched the one spelling most likely to appear in a
    # spreadsheet cell.
    if key in _SELF_OP_KEYS or key.replace(" ", "") in {"selfop", "selfoperated", "inhouse"}:
        return {"raw": raw, "operator_normalized": "Self-operated", "sub_brand": None,
                "relation": "self_op", "needs_review": False}

    for canonical in KNOWN_OPERATORS:
        if key == _norm(canonical):
            return {"raw": raw, "operator_normalized": canonical, "sub_brand": None,
                    "relation": "exact", "needs_review": False}

    if key in RENAMES:
        return {"raw": raw, "operator_normalized": RENAMES[key], "sub_brand": None,
                "relation": "rename", "needs_review": False}

    if key in SUB_BRANDS:
        return {"raw": raw, "operator_normalized": SUB_BRANDS[key], "sub_brand": raw,
                "relation": "sub_brand", "needs_review": False}

    if key in ACQUISITIONS:
        acquirer, year, confidence = ACQUISITIONS[key]
        # The company keeps its own identity. The acquirer is context for the span pairer.
        return {"raw": raw, "operator_normalized": raw.strip(), "sub_brand": None,
                "relation": "acquired", "acquired_by": acquirer, "acquired_year": year,
                "acquisition_confidence": confidence, "needs_review": confidence == "low"}

    return {"raw": raw, "operator_normalized": raw.strip(), "sub_brand": None,
            "relation": "unknown", "needs_review": True}


# ── Field specs ────────────────────────────────────────────────────────────────
# (name, type, required, enum, note). `required` means "must be present for the row to be
# usable", not "must be non-null" — an event with no date is still extracted, it is just
# marked needs_review. The filter never decides; Kiki does.

F = Tuple[str, str, bool, Optional[List[str]], str]

EVENT_FIELDS: list[F] = [
    ("event_id", "str", True, None, "stable hash of source_file + offset + operator + venue"),
    ("operator", "str", True, None, "as printed in the article"),
    ("operator_normalized", "str", True, None, "parent company, via normalize_operator"),
    ("sub_brand", "str", False, None, "Levy, Chartwells, Sportservice…"),
    ("venue_id", "str", False, None, "FK -> venue spine; null means unmatched"),
    ("institution", "str", False, None, "the entity that let the contract, if not the venue"),
    ("venue_name_as_written", "str", True, None, "NEVER normalized — the printed name dates the article"),
    ("event_type", "enum", True, EVENT_TYPES, ""),
    ("event_date", "date", False, None, "null allowed, but then needs_review"),
    ("date_precision", "enum", True, DATE_PRECISIONS, ""),
    ("first_outsourcing", "bool", False, None, "true only when the article says so"),
    ("contract_value_usd", "number", False, None, ""),
    ("contract_length_years", "number", False, None, ""),
    ("losing_bidders", "list", False, None, "named losing bidders"),
    ("source_publication", "str", True, None, "provenance is required — no anonymous rows"),
    ("source_date", "date", True, None, ""),
    ("source_title", "str", True, None, ""),
    ("source_file", "str", True, None, "path under articles/raw"),
    ("extraction_confidence", "number", True, None, "0-1"),
    ("needs_review", "bool", True, None, ""),
    ("notes", "str", False, None, ""),
    ("extras", "json", False, None, "watch-for list; promoted to columns only by Kiki"),
]

TENURE_FIELDS: list[F] = [
    ("tenure_id", "str", True, None, "pipeline key — NOT a workbook column"),
    ("venue_id", "str", False, None, "FK -> venue spine — NOT a workbook column (derived)"),
    ("venue_name", "str", True, None, ""),
    ("venue_type", "enum", True, TENURE_VENUE_TYPES, "workbook vocabulary, not spine vocabulary"),
    ("city", "str", False, None, ""),
    ("state", "str", False, None, "2-letter"),
    ("lat", "number", False, None, ""),
    ("lng", "number", False, None, ""),
    ("operator", "str", True, None, "as commonly known today"),
    ("operator_normalized", "str", True, None, "derived — NOT a workbook column"),
    ("start_date", "date", False, None, ""),
    ("start_precision", "enum", False, DATE_PRECISIONS, ""),
    ("end_date", "date", False, None, "blank unless end_status == ended"),
    ("end_precision", "enum", False, DATE_PRECISIONS, ""),
    ("end_status", "enum", True, END_STATUSES, "never blank"),
    ("exit_mode", "enum", False, EXIT_MODES, "only when end_status == ended"),
    ("derived_from", "list", False, None, "event_ids paired into this span — NOT a workbook column"),
    ("source", "str", True, None, "'personal knowledge' is valid; anonymous is not"),
    ("notes", "str", False, None, ""),
    ("extras", "json", False, None, ""),
]

HUNT_FIELDS: list[F] = [
    ("search_id", "str", True, None, "pipeline key — NOT a workbook column"),
    ("venue_or_operator", "str", True, None, ""),
    ("period_searched", "str", True, None, "e.g. 2005-2012"),
    ("where_searched", "str", True, None, "workbook's name for the plan's source_searched"),
    ("query_used", "str", False, None, "pipeline-only; folded into notes when written back"),
    ("date_of_search", "date", True, None, ""),
    ("result", "enum", True, HUNT_RESULTS, "nothing_found is DATA, not a failure"),
    ("notes", "str", False, None, ""),
]

# One federal prime award, after scope rules and the venue join. Column names on the left
# of each comment are the USAspending export columns they come from, so a future export with
# renamed headers fails loudly at load instead of quietly emitting nulls.
FEDERAL_FIELDS: list[F] = [
    ("award_id", "str", True, None, "contract_award_unique_key — unique per prime award"),
    ("piid", "str", False, None, "award_id_piid, the human-quotable contract number"),
    ("operator_raw", "str", True, None, "recipient_name, exactly as the registry prints it"),
    ("operator_normalized", "str", False, None, "via normalize_operator; blank when unresolved"),
    ("sub_brand", "str", False, None, ""),
    ("operator_relation", "str", True, None, "exact|rename|sub_brand|acquired|self_op|unknown"),
    ("awarding_agency", "str", False, None, "awarding_agency_name"),
    ("awarding_sub_agency", "str", False, None, "awarding_sub_agency_name — the useful one"),
    ("naics_code", "str", False, None, ""),
    ("naics_description", "str", False, None, ""),
    ("psc_code", "str", False, None, "product_or_service_code"),
    ("psc_description", "str", False, None, ""),
    ("start_date", "date", False, None, "period_of_performance_start_date"),
    ("end_date", "date", False, None, "period_of_performance_current_end_date"),
    ("fiscal_year", "number", False, None, "award_base_action_date_fiscal_year"),
    ("obligated_amount", "number", False, None, "total_obligated_amount — may be negative"),
    ("current_value", "number", False, None, "current_total_value_of_award"),
    ("pop_city", "str", False, None, "primary_place_of_performance_city_name"),
    ("pop_state", "str", False, None, "2-letter"),
    ("pop_zip", "str", False, None, "primary_place_of_performance_zip_4, first 5 — the join key"),
    ("pop_country", "str", False, None, "3-letter; scope keeps USA only"),
    ("description", "str", False, None, "prime_award_base_transaction_description, never normalized"),
    ("venue_id", "str", False, None, "FK -> venue spine; null is the normal case"),
    ("venue_match", "enum", True, FEDERAL_VENUE_MATCH, "how the venue was tied, or unmatched"),
    ("in_scope", "bool", True, None, ""),
    ("scope_reason", "enum", True, FEDERAL_EXCLUSIONS, "'in_scope' when kept"),
    ("source_file", "str", True, None, "which export this row came out of"),
]

# One venue's ACS context for one five-year vintage. Keyed on (venue_id, year) rather than
# on the ZCTA, because the ZCTA a venue belongs to changes mid-series and the venue does not.
ACS_FIELDS: list[F] = [
    ("venue_id", "str", True, None, "FK -> venue spine"),
    ("year", "number", True, None, "the ACS 5-year vintage, i.e. its last year"),
    ("zcta", "str", False, None, "the ZCTA used for THIS year; blank when unavailable"),
    ("zcta_vintage", "number", False, None, "2010 or 2020 — which ZCTA definition `zcta` is"),
    ("zcta_match", "enum", True, ACS_ZCTA_MATCH, "how much of the series this venue can be given"),
    ("workers_total", "number", False, None, "B08006_001E; the share denominators"),
    ("median_household_income", "number", False, None, "B19013_001E, NOMINAL vintage-year dollars"),
    ("transit_share", "number", False, None, "0-1; null when workers_total is 0"),
    ("long_commute_share", "number", False, None, "0-1; null when the B08303 total is 0"),
    ("source_file", "str", True, None, "which ACS export this row came out of"),
]

# Literal copies of Kiki's header rows. Order matters — these drive read and write.
WORKBOOK_TENURE_COLUMNS = [
    "venue_name", "venue_type", "city", "state", "lat", "lng", "operator",
    "start_date", "start_precision", "end_date", "end_precision", "end_status",
    "exit_mode", "source", "notes", "extras",
]

WORKBOOK_HUNT_COLUMNS = [
    "venue_or_operator", "period_searched", "where_searched", "date_of_search",
    "result", "notes",
]

# Fields the pipeline owns and the workbook must never grow a column for.
DERIVED_TENURE_FIELDS = ["tenure_id", "venue_id", "operator_normalized", "derived_from"]


# ── Validation ─────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _check_fields(row: dict[str, Any], fields: list[F], label: str) -> list[str]:
    problems = []
    spec = {f[0]: f for f in fields}
    for name, kind, required, enum, _note in fields:
        v = row.get(name)
        if required and _blank(v):
            problems.append(f"{label}: {name} is required but blank")
            continue
        if _blank(v):
            continue
        if enum and str(v) not in enum:
            problems.append(f"{label}: {name}={v!r} not in {enum}")
        if kind == "date" and not _DATE_RE.match(str(v)[:10]):
            problems.append(f"{label}: {name}={v!r} is not YYYY-MM-DD")
    unknown = set(row) - set(spec)
    if unknown:
        problems.append(f"{label}: unknown fields {sorted(unknown)} — use extras, not new columns")
    return problems


def _check_precision(date: Any, precision: Any, field: str) -> list[str]:
    """The workbook's stated convention: year-only dates are written as Jan 1."""
    if _blank(date) or _blank(precision):
        return []
    d = str(date)[:10]
    if not _DATE_RE.match(d):
        return []
    if precision == "year" and not d.endswith("-01-01"):
        return [f"{field}={d} has precision=year but is not Jan 1 (workbook convention)"]
    if precision == "month" and not d.endswith("-01"):
        return [f"{field}={d} has precision=month but is not the 1st"]
    return []


def validate_event(row: dict[str, Any]) -> list[str]:
    problems = _check_fields(row, EVENT_FIELDS, "event")
    problems += _check_precision(row.get("event_date"), row.get("date_precision"), "event_date")
    if _blank(row.get("event_date")) and not row.get("needs_review"):
        problems.append("event: no event_date, so needs_review must be true")
    return problems


def validate_tenure(row: dict[str, Any]) -> list[str]:
    problems = _check_fields(row, TENURE_FIELDS, "tenure")
    problems += _check_precision(row.get("start_date"), row.get("start_precision"), "start_date")
    problems += _check_precision(row.get("end_date"), row.get("end_precision"), "end_date")

    status = row.get("end_status")
    has_end = not _blank(row.get("end_date"))
    if status == "ended" and not has_end:
        problems.append("tenure: end_status=ended but end_date is blank")
    if status in ("ongoing", "unknown") and has_end:
        problems.append(f"tenure: end_status={status} but end_date is filled")
    if not _blank(row.get("exit_mode")) and status != "ended":
        problems.append(f"tenure: exit_mode set but end_status={status} (fill only when ended)")

    if has_end and not _blank(row.get("start_date")):
        if str(row["end_date"])[:10] < str(row["start_date"])[:10]:
            problems.append("tenure: end_date precedes start_date")
    return problems


def validate_hunt(row: dict[str, Any]) -> list[str]:
    return _check_fields(row, HUNT_FIELDS, "hunt_log")


def validate_federal(row: dict[str, Any]) -> list[str]:
    """A federal award row, after scope and the venue join.

    The checks that matter here are the ones that keep `in_scope` honest. A row that says
    it is in scope while carrying the reason it was excluded — or an excluded row still
    holding a venue_id — is a bug that would otherwise show up as a wrong number on a map,
    which is the hardest place to notice it.
    """
    problems = _check_fields(row, FEDERAL_FIELDS, "federal")

    in_scope = bool(row.get("in_scope"))
    reason = row.get("scope_reason")
    if in_scope and reason != "in_scope":
        problems.append(f"federal: in_scope is true but scope_reason={reason!r}")
    if not in_scope and reason == "in_scope":
        problems.append("federal: in_scope is false but scope_reason says it was kept")

    # A venue match on an excluded row would put a dot on the map for work the scope rule
    # already said does not belong there.
    if not in_scope and not _blank(row.get("venue_id")):
        problems.append(f"federal: excluded ({reason}) but still carries venue_id")
    matched = row.get("venue_match") != "unmatched"
    if matched != (not _blank(row.get("venue_id"))):
        problems.append(
            f"federal: venue_match={row.get('venue_match')!r} disagrees with "
            f"venue_id={row.get('venue_id')!r}"
        )

    # An unresolved operator is exactly what `operator_unresolved` means, so the two must
    # never disagree — that is the check that catches a crosswalk edit breaking scope.
    resolved = row.get("operator_relation") not in (None, "", "unknown")
    if resolved and reason == "operator_unresolved":
        problems.append("federal: scope_reason=operator_unresolved but the operator resolved")
    if not resolved and in_scope:
        problems.append("federal: kept in scope with an unresolved operator")

    if not _blank(row.get("start_date")) and not _blank(row.get("end_date")):
        if str(row["end_date"])[:10] < str(row["start_date"])[:10]:
            problems.append("federal: end_date precedes start_date")
    return problems


def validate_acs(row: dict[str, Any]) -> list[str]:
    """One venue's ACS context for one vintage.

    The checks here all guard the same failure: context attached to the wrong geography.
    A share outside 0-1 or a ZCTA of the wrong vintage does not crash anything — it renders
    as a plausible number next to a venue, which is the worst possible way to be wrong.
    """
    problems = _check_fields(row, ACS_FIELDS, "acs")

    year = row.get("year")
    zcta = row.get("zcta")
    vintage = row.get("zcta_vintage")
    match = row.get("zcta_match")

    # The vintage is a function of the year, not a free choice. If these ever disagree the
    # row is quoting one decade's neighbourhood under another decade's boundaries.
    if isinstance(year, (int, float)) and not _blank(zcta):
        expected = 2010 if year <= ACS_LAST_2010_VINTAGE else 2020
        if vintage != expected:
            problems.append(
                f"acs: year {year:.0f} needs the {expected} ZCTA vintage, got {vintage!r}"
            )

    # A venue resolved in only one era must be blank in the other, not silently borrowing
    # the ZCTA it does have.
    if match == "no_zcta" and not _blank(zcta):
        problems.append("acs: zcta_match=no_zcta but a zcta is present")
    if match == "2020_only" and vintage == 2010:
        problems.append("acs: zcta_match=2020_only but the row uses the 2010 vintage")
    if match == "2010_only" and vintage == 2020:
        problems.append("acs: zcta_match=2010_only but the row uses the 2020 vintage")

    if _blank(zcta):
        for measure in ("workers_total", "median_household_income",
                        "transit_share", "long_commute_share"):
            if not _blank(row.get(measure)):
                problems.append(f"acs: no zcta but {measure} is populated")

    for share in ("transit_share", "long_commute_share"):
        v = row.get(share)
        if v is not None and not (0.0 <= float(v) <= 1.0):
            problems.append(f"acs: {share}={v} is outside 0-1")

    workers = row.get("workers_total")
    if workers is not None and float(workers) < 0:
        problems.append(f"acs: workers_total={workers} is negative")
    # Shares are computed from a denominator; a share with no denominator is arithmetic
    # that happened somewhere it should not have.
    if workers in (None, 0) and row.get("transit_share") is not None:
        problems.append("acs: transit_share present with no workers to divide by")
    return problems


# ── JSON Schema for the extraction call (Phase 1.2) ────────────────────────────

_JSON_TYPES = {
    "str": {"type": ["string", "null"]},
    "date": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
    "bool": {"type": ["boolean", "null"]},
    "number": {"type": ["number", "null"]},
    "list": {"type": ["array", "null"], "items": {"type": "string"}},
    "json": {"type": ["object", "null"]},
}


def event_json_schema() -> dict[str, Any]:
    """The schema handed to the model. Generated from EVENT_FIELDS so the prompt and the
    validator cannot drift apart — the usual failure mode of LLM extraction pipelines."""
    props: dict[str, Any] = {}
    for name, kind, _req, enum, note in EVENT_FIELDS:
        if name == "event_id":
            continue  # assigned by the pipeline, not the model
        prop = {"type": ["string", "null"], "enum": [*enum, None]} if enum else dict(_JSON_TYPES[kind])
        if note:
            prop["description"] = note
        props[name] = prop
    return {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "description": "Zero or more contract events. Zero is a valid, expected answer.",
                "items": {
                    "type": "object",
                    "properties": props,
                    "required": [n for n, _k, req, _e, _o in EVENT_FIELDS if req and n != "event_id"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["events"],
        "additionalProperties": False,
    }
