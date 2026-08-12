"""The extraction prompt: one article in, zero or more contract events out.

Three things are deliberately *not* left to the model's judgment, because each one is a
place where an LLM pipeline silently invents data:

  * **`venue_id`** is only ever copied from the candidate list `candidates.py` supplies.
    The model is never shown the spine, so it has nothing to hallucinate from, and
    `validate_extraction` re-checks that every id it returned was on the list.
  * **The operator crosswalk** is rendered into the prompt from `schema.py`'s own
    dictionaries. If someone adds a sub-brand to `SUB_BRANDS`, the prompt changes with it.
    The model still gets `normalize_operator` run over its answer afterwards, which wins.
  * **The response schema** is `event_json_schema()`, generated from the same `EVENT_FIELDS`
    the validator reads. The prompt and the validator cannot disagree about what a field is.

The hardest instruction here is the one about RFPs. Trade press writes "Aramark is expected
to be awarded" and "the authority will seek bids" in the same register as an actual award,
and a model rewarded for finding things will turn both into `won`. A phantom win poisons
the tenure table worse than a missed one: a missed event leaves a gap the hunt log can
record, while a phantom event fabricates a span that never existed.

    .venv/bin/python -m pipeline.extract.prompt        # print a rendered example
"""

from __future__ import annotations

import json
from typing import Any

from ..schema import (
    ACQUISITIONS,
    EVENT_TYPES,
    KNOWN_OPERATORS,
    RENAMES,
    SUB_BRANDS,
    event_json_schema,
)

MODEL = "claude-opus-4-6"
MAX_BODY_CHARS = 40_000

RESPONSE_SCHEMA = event_json_schema()


# ── The operator crosswalk, rendered from schema.py so it cannot drift ─────────

def _crosswalk_block() -> str:
    renames = ", ".join(f"{k} = {v}" for k, v in sorted(RENAMES.items()))
    subs: dict[str, list[str]] = {}
    for brand, parent in sorted(SUB_BRANDS.items()):
        subs.setdefault(parent, []).append(brand)
    sub_lines = "\n".join(f"    {parent}: {', '.join(v)}" for parent, v in sorted(subs.items()))
    acq = "\n".join(
        f"    {k} was bought by {v[0]} in {v[1]} — keep it as \"{k}\", do NOT write {v[0]}"
        for k, v in sorted(ACQUISITIONS.items())
    )
    # `sorted` is not cosmetic here. KNOWN_OPERATORS is a set, and Python randomizes string
    # hashing per process, so this line came out in a different order on every run. That changes
    # the prompt text, which changes the payload hash, which is the cache key — so the "an
    # interrupted run re-reads the calls it already paid for" promise in `run.py` was never
    # true. Measured: two consecutive runs over the same 5 articles shared 0 cache entries and
    # were billed twice. Over the full 366-article corpus that is the difference between a
    # resumable two-hour run and one that has to be paid for again from the top every time it
    # is interrupted. Every other list in this function was already sorted; this one was missed.
    return f"""Known parents: {', '.join(sorted(KNOWN_OPERATORS))}

  RENAMES — same company, new name. Normalize freely.
    {renames}

  SUB-BRANDS — a division of a parent. Put the division in `sub_brand` and the parent in
  `operator_normalized`.
{sub_lines}

  ACQUISITIONS — a different company that was later bought. NEVER normalize these to the
  acquirer. A 2005 Centerplate contract was not a Sodexo contract; folding it in invents a
  Sodexo run that no article reports and that the tenure table would then assert as fact.
{acq}"""


SYSTEM = f"""You read one newspaper or trade-press article and report the food-service
contract events it states as fact. You are building a historical record of who held the
concessions and catering contract at US stadiums, arenas and convention centers, so the
standard is what the article *reports*, not what it implies or predicts.

Return zero or more events. **Zero is a correct and common answer.** Most articles that
mention a venue and a caterer are not reporting a contract event at all.

## What counts as an event

One event = one operator + one venue + one thing that happened, with the event types:

  won        — a contract was awarded to this operator (reported as decided, not expected)
  lost       — this operator's contract ended because someone else got it
  renewed    — an existing contract with this operator was extended
  expired    — the contract ended with no successor named
  self_op    — the venue took food service in-house
  strike     — labor action by this operator's workers at this venue
  violation  — health, wage, or contract violation attributed to this operator
  initiative — a program announcement (sustainability, local sourcing, menu overhaul)

An article about a switch reports **two** events: a `lost` for the incumbent and a `won`
for the newcomer. Emit both. Do not emit a `lost` for an incumbent the article does not
name — "replaces the previous vendor" identifies no one.

## What is NOT an event

  * An RFP, a solicitation, a bid deadline, a shortlist, a proposal under consideration.
  * "Is expected to win", "is the frontrunner", "sources say", "is in talks", "is likely to".
  * A contract described only as a possibility, a plan, or a recommendation to a board that
    has not voted.
  * Catering a single game, convention or one-off event.
  * A restaurant review, a menu item, a chef profile, a stadium food ranking.
  * The operator merely being present ("hot dogs from Aramark's stand") with no change.
  * **A labor contract between the operator and a union.** "The union's contract with Aramark
    expired April 1" is a collective bargaining agreement, not the concessions contract, and
    the operator keeps running the venue throughout. Only `event_type` = `strike` applies to
    labor, and only when workers actually strike — not for picketing, contract talks, a
    rejected offer, or a strike vote that has not happened. If a labor dispute is all the
    article reports, return an empty `events` list.

If the article is about a pending decision, return an empty `events` list. Do not downgrade
it to a low-confidence `won`. A phantom contract is worse than a missing one: a gap can be
searched for later, but a fabricated award silently becomes an asserted fact.

The exception is `expired` — an article stating a contract *will* end on a known date is
reporting a decided fact, not a prediction. Use the stated end date.

## Venues

`venue_id` MUST be copied verbatim from the CANDIDATE VENUES list, or be null. Never
construct one, never guess from the format of the examples. If no candidate is the venue
the article names, use null and set `needs_review` to true — an unmatched venue is a real
finding about our venue list, not something to paper over.

Each candidate carries `plausible_at_article_date`. This is a flag, not a filter. A 2005
article can legitimately discuss a stadium demolished in 1968. But if several candidates
share a name (there are three Madison Square Gardens), prefer the one whose dates fit the
contract being described, and say so in `notes`.

`venue_name_as_written` is the venue name **exactly as the article prints it** — "Enron
Field", not "Daikin Park"; "the Garden", not "Madison Square Garden". Never normalize it.
Which name a paper used is itself evidence of when the events happened.

`institution` is the body that let the contract when it is not the venue itself — a
university, a stadium authority, a county, a team. Leave null when the venue is the
contracting party.

## Operators

`operator` is the name **as printed**. `operator_normalized` is the parent company:

{_crosswalk_block()}

An operator not on any of these lists is fine. Copy the printed name into both fields and
set `needs_review` to true.

If the article says the venue took food service in-house, `operator` is what the article
calls it and `operator_normalized` is "Self-operated", with `event_type` = `self_op`.

## Dates

`event_date` is when the event **happened or takes effect**, not when the article ran.
"Aramark won a contract beginning with the 2006 season", published 2005-11-02, is
`event_date` 2006-01-01 with `date_precision` = `year`.

  exact   — a full date is stated
  month   — a month and year are stated; use the 1st
  year    — a year or a season is stated; use January 1
  approx  — inferred from context ("last spring", "three years ago")

Never use the publication date as the event date to fill a hole. If the article gives no
usable date, leave `event_date` null, set `date_precision` = `approx`, and set
`needs_review` to true.

`contract_length_years` is the stated term. `contract_value_usd` is the total contract
value in dollars — convert "$12 million" to 12000000, and if the figure is annual rather
than total, put the term in `notes` rather than multiplying it yourself.

`first_outsourcing` is true **only** when the article says this is the first time the venue
contracted food service out. Leave it null otherwise; false asserts the opposite.

## Source fields

`source_publication`, `source_date`, `source_title` and `source_file` are copied exactly
from the ARTICLE header block below. Do not re-derive, re-format or guess them. If a header
value is missing, copy null — provenance we do not have is not provenance we invent.

## Confidence and review

`extraction_confidence` is 0-1: how sure you are the event happened as described.
  0.9-1.0  the article states it plainly and unambiguously
  0.7-0.9  clearly stated, one detail (date, venue, exact operator) is fuzzy
  0.4-0.7  reported at a remove, or the venue/operator identity is uncertain
  below 0.4 you are mostly inferring — ask whether this is an event at all

Set `needs_review` to true whenever: no `venue_id` matched, the operator is not on the
crosswalk, several candidates fit, the date is inferred, or the article contradicts itself.
Explain the reason in `notes`. `notes` is for the human reading the row, not a summary of
the article — write what a reviewer would need to check.

Extract the event even when it is ambiguous. Flag it; do not drop it. A flagged row can be
resolved by a person; a dropped one is invisible.

## extras

`extras` is a free-form object for facts worth keeping that have no column yet. Only Kiki
promotes these to real columns, so put things there rather than forcing them into `notes`:
subcontractors and minority/MWBE partners, union or local number, commission or revenue
share percentage, promised capital investment, exclusivity or pouring rights, the number of
concession stands, and the named incumbent when the article does not say who they were.

Return only JSON matching the schema. Field types: {', '.join(EVENT_TYPES)} are the only
legal `event_type` values."""


# ── Rendering one article ──────────────────────────────────────────────────────

_CAND_FIELDS = [
    ("venue_id", "venue_id"),
    ("canonical_name", "name"),
    ("matched_as", "text matched"),
    ("venue_type", "type"),
    ("city", "city"),
    ("state", "state"),
    ("opened_date", "opened"),
    ("closed_date", "closed"),
    ("capacity", "seats"),
    ("name_used", "name used"),
    ("plausible_at_article_date", "plausible at article date"),
    ("name_is_ambiguous", "name shared with another venue"),
]


def render_candidates(candidates: list[dict[str, Any]]) -> str:
    """One block per candidate. Verbose on purpose — the dates are what disambiguates the
    three Madison Square Gardens, so hiding them would make the choice unmakeable."""
    if not candidates:
        return (
            "CANDIDATE VENUES: none.\n"
            "No venue in our list is named in this article. Every `venue_id` must therefore\n"
            "be null. This does not mean there is no event — extract it with a null venue_id\n"
            "and needs_review = true."
        )
    lines = [f"CANDIDATE VENUES ({len(candidates)}) — `venue_id` may only be one of these, or null:"]
    for c in candidates:
        parts = [f"{label}={c[key]!r}" for key, label in _CAND_FIELDS if c.get(key) is not None]
        lines.append("  - " + "; ".join(parts))
    return "\n".join(lines)


def render_article(article: dict[str, Any]) -> str:
    body = article.get("body_text") or ""
    truncated = len(body) > MAX_BODY_CHARS
    if truncated:
        body = body[:MAX_BODY_CHARS]
    header = "\n".join(
        f"  {field}: {article.get(field)!r}"
        for field in ("source_publication", "source_date", "source_title", "source_file")
    )
    note = "\n\n[body truncated]" if truncated else ""
    return f"ARTICLE header — copy these into every event verbatim:\n{header}\n\nBODY:\n{body}{note}"


def build_messages(
    article: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """The user turn. `SYSTEM` is the system prompt; `RESPONSE_SCHEMA` is the tool/schema."""
    return [
        {
            "role": "user",
            "content": (
                f"{render_candidates(candidates)}\n\n"
                f"{render_article(article)}\n\n"
                "Report the contract events this article states as fact. Return an empty "
                "list if it reports none."
            ),
        }
    ]


# ── Checking the answer before it is trusted ──────────────────────────────────

def validate_extraction(
    events: list[dict[str, Any]], candidates: list[dict[str, Any]], article: dict[str, Any]
) -> list[str]:
    """Problems with what the model returned, independent of `validate_event`'s field rules.

    Schema conformance is not the risk. The risks are a `venue_id` that was never offered
    and source fields quietly rewritten, both of which pass any type check.
    """
    allowed = {c["venue_id"] for c in candidates}
    problems = []
    for i, ev in enumerate(events):
        vid = ev.get("venue_id")
        if vid and vid not in allowed:
            problems.append(f"event {i}: venue_id {vid!r} was not offered as a candidate")
        for field in ("source_publication", "source_date", "source_title", "source_file"):
            if ev.get(field) != article.get(field):
                problems.append(
                    f"event {i}: {field} was rewritten "
                    f"({ev.get(field)!r} != article's {article.get(field)!r})"
                )
    return problems


def main() -> None:
    from .candidates import build_index, find_for_article

    article = {
        "source_publication": "St. Louis Post-Dispatch",
        "source_date": "2005-11-02",
        "source_title": "Cardinals pick concessionaire for new ballpark",
        "source_file": "articles/raw/usb1/postdispatch_2005.txt",
        "body_text": (
            "The Cardinals said Tuesday that Aramark Corp. will run concessions at the new "
            "Busch Stadium when it opens for the 2006 season, ending a four-decade run by "
            "Sportservice at the old park. The 10-year deal is worth about $30 million. "
            "Levy Restaurants and Centerplate also bid. Separately, the convention and "
            "visitors commission said it will seek proposals next spring for food service "
            "at America's Center."
        ),
    }
    candidates = find_for_article(article, build_index())
    print(SYSTEM)
    print("\n" + "=" * 78 + "\n")
    print(build_messages(article, candidates)[0]["content"])
    print("\n" + "=" * 78 + "\n")
    print(json.dumps(RESPONSE_SCHEMA, indent=2)[:600] + "\n  ...")


if __name__ == "__main__":
    main()
