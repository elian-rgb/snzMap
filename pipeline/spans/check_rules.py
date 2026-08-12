"""Gate for the span pairer — does each pairing rule still do what it claims?

There is no real event data yet, and there will not be until the USB articles arrive. But
the pairing rules are pure logic over a timeline, so they can be checked now against
timelines written by hand. That is the same bargain `spine/spotcheck.py` makes: the answer
key is written separately from the code under test, and it is written *before* the code is
trusted rather than after it passes.

Each scenario is one rule from `pair.py`'s docstring, stated as events in and spans out. A
change that quietly turns `unknown` into `ongoing`, or that starts asserting an end date
nobody reported, fails here.

    .venv/bin/python -m pipeline.spans.check_rules
"""

from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from .pair import pair

AS_OF = dt.date(2026, 1, 1)   # fixed, so `ongoing` vs `unknown` is reproducible

V = "wd-TEST"
VENUES = {V: {"venue_id": V, "canonical_name": "Test Arena", "venue_type": "arena",
              "city": "Denver", "state": "CO", "lat": 39.7, "lng": -105.0}}

_n = [0]


def ev(op: str, kind: str, date: str | None, precision: str | None = "exact",
       venue_id: str | None = V) -> dict[str, Any]:
    _n[0] += 1
    return {"event_id": f"e{_n[0]}", "operator": op, "operator_normalized": op,
            "venue_id": venue_id, "venue_name_as_written": "Test Arena",
            "event_type": kind, "event_date": date, "date_precision": precision,
            "source_publication": "The Post", "source_date": date or "2000-01-01",
            "source_title": "t", "source_file": "f.txt"}


# (label, events, expected spans as {operator: (start, end, end_status, exit_mode)})
SCENARIOS: list[tuple[str, list[dict[str, Any]], dict[str, tuple]]] = [
    (
        "won then lost is one closed span",
        [ev("Aramark", "won", "2004-03-01"), ev("Aramark", "lost", "2011-06-15")],
        {"Aramark": ("2004-03-01", "2011-06-15", "ended", "lost_bid")},
    ),
    (
        "two papers covering one award make one span, not two",
        [ev("Aramark", "won", "2004-03-01"), ev("Aramark", "won", "2004-03-06")],
        {"Aramark": ("2004-03-01", None, "unknown", None)},
    ),
    (
        "renewals extend rather than restart",
        [ev("Compass", "won", "2015-01-01", "year"),
         ev("Compass", "renewed", "2020-01-01", "year"),
         ev("Compass", "renewed", "2025-01-01", "year")],
        {"Compass": ("2015-01-01", None, "ongoing", None)},
    ),
    (
        "recent evidence means ongoing; stale evidence means unknown",
        [ev("Sodexo", "won", "1998-01-01", "year")],
        {"Sodexo": ("1998-01-01", None, "unknown", None)},
    ),
    (
        "a loss with no reported award still yields a run, with unknown start",
        [ev("Delaware North", "lost", "2007-08-01", "month")],
        {"Delaware North": (None, "2007-08-01", "ended", "lost_bid")},
    ),
    (
        "an expiry is an ending, but not a lost bid",
        [ev("Legends", "won", "2001-01-01", "year"),
         ev("Legends", "expired", "2009-01-01", "year")],
        {"Legends": ("2001-01-01", "2009-01-01", "ended", "other")},
    ),
    (
        "a strike proves presence but never opens a contract",
        [ev("Aramark", "strike", "2008-04-01", "month")],
        {"Aramark": (None, None, "unknown", None)},
    ),
    (
        "presence then a loss is one span ending at the loss",
        [ev("Aramark", "strike", "2008-04-01", "month"),
         ev("Aramark", "lost", "2011-07-01", "month")],
        {"Aramark": (None, "2011-07-01", "ended", "lost_bid")},
    ),
    (
        "a successor closes the previous run, cause unknown",
        [ev("Aramark", "won", "2008-09-01", "month"),
         ev("Compass", "won", "2016-01-01", "year")],
        {"Aramark": ("2008-09-01", "2016-01-01", "ended", "unknown"),
         "Compass": ("2016-01-01", None, "unknown", None)},
    ),
    (
        "a self-operated successor names the cause",
        [ev("Compass", "won", "2012-01-01", "year"),
         ev("Self-operated", "self_op", "2019-01-01", "year")],
        {"Compass": ("2012-01-01", "2019-01-01", "ended", "self_op_conversion"),
         "Self-operated": ("2019-01-01", None, "unknown", None)},
    ),
    (
        "a re-award with no reported end does not overlap itself",
        [ev("Aramark", "won", "1995-01-01", "year"),
         ev("Aramark", "won", "2003-01-01", "year"),
         ev("Aramark", "lost", "2014-01-01", "year")],
        {"Aramark": ("1995-01-01", "2014-01-01", "ended", "lost_bid")},
    ),
    (
        "an undated event cannot be placed but is never dropped",
        [ev("Legends", "won", None, None)],
        {"Legends": (None, None, "unknown", None)},
    ),
    (
        "a sub-brand and its parent are one run, not two",
        [ev("Compass", "won", "2010-01-01", "year"),
         ev("Compass", "renewed", "2014-01-01", "year")],
        {"Compass": ("2010-01-01", None, "unknown", None)},
    ),
]

# Rules that are about flags rather than dates, checked separately.
FLAG_CHECKS = [
    ("succession ends are marked as inferred, not reported",
     [ev("Aramark", "won", "2008-09-01", "month"), ev("Compass", "won", "2016-01-01", "year")],
     lambda rows: next(r for r in rows if r["operator"] == "Aramark")["extras"]
     .get("end_inferred_from") == "succession"),
    ("two operators holding one venue at once is flagged, not resolved",
     [ev("Aramark", "won", "2000-01-01", "year"), ev("Aramark", "lost", "2010-01-01", "year"),
      ev("Delaware North", "won", "2005-01-01", "year"),
      ev("Delaware North", "lost", "2012-01-01", "year")],
     lambda rows: all(r["extras"].get("overlaps_with") for r in rows)),
    ("a dateless span is not reported as overlapping everything",
     [ev("Aramark", "won", "2000-01-01", "year"), ev("Legends", "won", None, None)],
     lambda rows: not any(r["extras"].get("overlaps_with") for r in rows)),
    ("an unmatched venue is kept, flagged, and not mappable",
     [ev("Sodexo", "won", "2009-01-01", "year", venue_id=None)],
     lambda rows: rows[0]["venue_id"] is None and rows[0]["extras"]["needs_review"]),
    ("every event lands in a span or in unusable_events",
     [ev("Aramark", "won", "2004-01-01", "year"), ev("Aramark", "strike", "2006-01-01", "year"),
      ev("Aramark", "lost", "2009-01-01", "year")],
     None),   # checked via stats, below
]


def _actual(rows: list[dict[str, Any]]) -> dict[str, tuple]:
    return {r["operator"]: (r["start_date"], r["end_date"], r["end_status"], r["exit_mode"])
            for r in rows}


def main() -> int:
    failures: list[str] = []
    schema_problems: list[str] = []

    for label, events, expected in SCENARIOS:
        result = pair(events, VENUES, as_of=AS_OF)
        schema_problems += [f"{label}: {p}" for p in result["problems"]]
        actual = _actual(result["tenure"])
        if actual != expected:
            failures.append(f"{label}\n      expected {expected}\n      got      {actual}")
        if result["stats"]["events_unaccounted"]:
            failures.append(f"{label}: {result['stats']['events_unaccounted']} event(s) vanished")

    for label, events, check in FLAG_CHECKS:
        result = pair(events, VENUES, as_of=AS_OF)
        schema_problems += [f"{label}: {p}" for p in result["problems"]]
        ok = (result["stats"]["events_unaccounted"] == 0 if check is None
              else check(result["tenure"]))
        if not ok:
            failures.append(label)

    total = len(SCENARIOS) + len(FLAG_CHECKS)
    print(f"span pairing rules: {total - len(failures)}/{total} pass")
    print(f"schema problems   : {len(schema_problems)}")

    for f in failures:
        print(f"  FAIL  {f}")
    for p in schema_problems[:10]:
        print(f"  SCHEMA  {p}")

    if failures or schema_problems:
        return 1
    print("\nPASS — every span the pairer produced also validates against TENURE_FIELDS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
