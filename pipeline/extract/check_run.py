"""Gate for the extraction runner — does it still refuse to trust the model?

There is no API key in this environment and no real article corpus yet, so the live call is
the one thing here that cannot be exercised. Everything on either side of it can, and it is
where all the logic lives: the runner's job is not to call an API, it is to decide what to
believe about the answer.

The trick is that `PoliteSession` caches on the payload hash. Writing a hand-crafted
response into `cache_path_for(...)` makes `post_json` return it without touching the
network, so `run()` executes for real — real prompt, real candidate finder, real repairs,
real validation — against answers chosen to be wrong in specific ways.

Each scenario is one way an extraction pipeline silently invents data:

  * a `venue_id` that was never offered           -> nulled and counted, never kept
  * a source field quietly rewritten              -> restored from the article
  * an acquired company folded into its acquirer  -> refused; Centerplate stays Centerplate
  * a date whose precision contradicts its value  -> rejected, NOT snapped to fit
  * an article about the weather                  -> zero events is a correct answer

    .venv/bin/python -m pipeline.extract.check_run
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ..common.http import PoliteSession
from ..schema import validate_event
from .candidates import build_index, find_for_article
from .run import TOOL_NAME, build_payload, check_response, run

SESSION_NAME = "extract_check"  # its own raw/ dir, so fixtures never mix with real bytes

ARTICLES: list[dict[str, Any]] = [
    {"source_file": "check/busch.txt", "source_offset": 0,
     "source_publication": "St. Louis Post-Dispatch", "source_date": "2005-11-02",
     "source_title": "Cardinals pick concessionaire for new ballpark",
     "body_text": (
         "The Cardinals said Tuesday that Aramark Corp. will run concessions at the new "
         "Busch Stadium when it opens for the 2006 season, ending a four-decade run by "
         "Sportservice at the old park. The 10-year deal is worth about $30 million. "
         "Levy Restaurants and Centerplate also bid.")},
    {"source_file": "check/soldier.txt", "source_offset": 4211,
     "source_publication": "Chicago Tribune", "source_date": "2011-06-14",
     "source_title": "Soldier Field food workers authorize strike",
     "body_text": (
         "Workers who staff concession stands at Soldier Field voted Monday to authorize a "
         "strike against Sodexho, the stadium's food service contractor.")},
    {"source_file": "check/weather.txt", "source_offset": 900,
     "source_publication": "Daily Herald", "source_date": "1998-03-09",
     "source_title": "Spring storms close area schools",
     "body_text": "Six inches of snow fell across the region overnight, closing schools."},
]


def _event(**over: Any) -> dict[str, Any]:
    base = {
        "operator": "Aramark", "operator_normalized": "Aramark", "sub_brand": None,
        "venue_id": None, "institution": None, "venue_name_as_written": "Busch Stadium",
        "event_type": "won", "event_date": "2005-11-01", "date_precision": "exact",
        "first_outsourcing": None, "contract_value_usd": 30000000,
        "contract_length_years": 10, "losing_bidders": ["Levy Restaurants", "Centerplate"],
        "source_publication": "St. Louis Post-Dispatch", "source_date": "2005-11-02",
        "source_title": "Cardinals pick concessionaire for new ballpark",
        "source_file": "check/busch.txt",
        "extraction_confidence": 0.95, "needs_review": False, "notes": None, "extras": None,
    }
    base.update(over)
    return base


def answers(candidates_by_article: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """What the model 'returns' for each article — wrong on purpose."""
    real_vid = candidates_by_article[0][0]["venue_id"] if candidates_by_article[0] else None
    return [
        [
            # 1. a good row, but pointing at a venue_id that was never on the candidate list
            _event(venue_id="wd-Q000000-NEVER-OFFERED"),
            # 2. a good row that quietly rewrote the paper's name
            _event(venue_id=real_vid, operator="Centerplate", event_type="lost",
                   source_publication="The Post-Dispatch"),
            # 3. a sub-brand, to prove the parent is filled in from schema.py's crosswalk
            _event(venue_id=real_vid, operator="Sportservice", event_type="lost",
                   event_date="2005-01-01", date_precision="year"),
            # 4. an operator nobody has heard of — kept, but flagged for a person
            _event(venue_id=real_vid, operator="Bill's Catering of Ladue",
                   event_type="lost", event_date="2005-01-01", date_precision="year"),
            # 5. precision says year, date is not Jan 1 — a judgement call, so it is rejected
            _event(venue_id=real_vid, operator="Aramark", event_type="renewed",
                   event_date="2005-06-15", date_precision="year"),
        ],
        [
            _event(operator="Sodexho", event_type="strike", event_date="2011-06-13",
                   venue_name_as_written="Soldier Field",
                   venue_id=(candidates_by_article[1][0]["venue_id"]
                             if candidates_by_article[1] else None),
                   source_publication="Chicago Tribune", source_date="2011-06-14",
                   source_title="Soldier Field food workers authorize strike",
                   source_file="check/soldier.txt", contract_value_usd=None,
                   contract_length_years=None, losing_bidders=None),
        ],
        [],  # the weather article reports no contract event
    ]


def seed(session: PoliteSession) -> list[list[dict[str, Any]]]:
    index = build_index()
    cands = [find_for_article(a, index) for a in ARTICLES]
    for article, events in zip(ARTICLES, answers(cands)):
        payload = build_payload(article, find_for_article(article, index))
        body = json.dumps({
            "id": "msg_check", "type": "message", "role": "assistant",
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "tu_1", "name": TOOL_NAME,
                         "input": {"events": events}}],
            "usage": {"input_tokens": 3000, "output_tokens": 400,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })
        from .run import article_key
        session.cache_path_for(payload, article_key(article)).write_text(body)
    return cands


def main() -> int:
    session = PoliteSession(SESSION_NAME, min_interval_s=0.0)
    cands = seed(session)
    r = run(ARTICLES, session=session, progress_every=0)

    events, rejected = r["events"], r["rejected"]
    repairs = [x for a in r["per_article"] for x in a.get("repairs", [])]
    failures: list[str] = []
    ran: list[str] = []

    def want(label: str, ok: bool) -> None:
        ran.append(label)
        if not ok:
            failures.append(label)

    want("no call errored (cache should have satisfied all three)",
         not any(a.get("error") for a in r["per_article"]))
    want("the weather article produced zero events",
         r["per_article"][2].get("events") == 0)

    want("an off-list venue_id was nulled, not kept",
         all(e["venue_id"] != "wd-Q000000-NEVER-OFFERED" for e in events))
    want("nulling an off-list venue_id forces needs_review",
         any(e["needs_review"] and e["venue_id"] is None for e in events))
    want("the off-list venue_id was counted as a repair",
         any("not offered" in x for x in repairs))

    want("a rewritten source_publication was restored from the article",
         all(e["source_publication"] == "St. Louis Post-Dispatch"
             for e in events if e["source_file"] == "check/busch.txt"))
    want("the rewrite was counted as a repair",
         any("rewritten by model" in x for x in repairs))

    want("Centerplate was NOT folded into Sodexo",
         all(e["operator_normalized"] == "Centerplate"
             for e in events if e["operator"] == "Centerplate"))
    want("Sodexho was normalized to Sodexo",
         all(e["operator_normalized"] == "Sodexo"
             for e in events if e["operator"] == "Sodexho"))
    sportservice = [e for e in events if e["operator"] == "Sportservice"]
    want("a sub-brand resolves to its parent and keeps its own name",
         len(sportservice) == 1 and sportservice[0]["operator_normalized"] == "Delaware North"
         and sportservice[0]["sub_brand"] == "Sportservice")
    unknown_op = [e for e in events if e["operator"] == "Bill's Catering of Ladue"]
    want("an operator the crosswalk does not know is kept but flagged",
         len(unknown_op) == 1 and unknown_op[0]["needs_review"]
         and unknown_op[0]["operator_normalized"] == "Bill's Catering of Ladue")

    want("a year-precision date that is not Jan 1 was rejected, not snapped",
         any("precision=year" in p for x in rejected for p in x["problems"]))
    want("rejected rows were kept, not dropped", len(rejected) == 1)
    want("no answer went missing (every returned event was kept or rejected)",
         len(events) + len(rejected)
         == sum(a.get("events", 0) for a in r["per_article"]))
    want("every emitted event validates against EVENT_FIELDS",
         all(not validate_event(e) for e in events))

    want("event_id is deterministic across runs",
         [e["event_id"] for e in events]
         == [e["event_id"] for e in run(ARTICLES, session=session, progress_every=0)["events"]])

    # A truncated tool call must be retryable, not quietly accepted as "zero events".
    truncated = json.dumps({"stop_reason": "max_tokens", "content": [
        {"type": "tool_use", "name": TOOL_NAME, "input": {"events": []}}]})
    try:
        check_response(truncated)
        want("a max_tokens truncation is rejected", False)
    except ValueError:
        want("a max_tokens truncation is rejected", True)

    total = len(ran)
    print(f"extraction runner: {total - len(failures)}/{total} pass")
    print(f"  candidates found : {[len(c) for c in cands]}")
    print(f"  events kept      : {len(events)}   rejected: {len(rejected)}")
    print(f"  repairs applied  : {len(repairs)}")
    for x in repairs:
        print(f"    ~ {x}")
    for x in rejected:
        print(f"    x {x['problems']}")
    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        return 1
    print("\nPASS — the runner repaired what it may, rejected what it may not, "
          "and dropped nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
