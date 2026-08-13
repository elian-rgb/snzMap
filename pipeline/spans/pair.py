"""Pair contract events into tenure spans — the deliverable, and the actual hard part.

An article reports a moment: "Aramark won the Coors Field contract in 2004." The tenure
table wants a *run*: Aramark held Coors Field from 2004 until 2011. Nothing in any single
article says that. It is produced here, by putting every event about one operator at one
venue on a timeline and reading the shape.

The rules, stated plainly because each one is a decision that can be wrong:

  won            opens a span
  renewed        extends an open span; opens one with an UNKNOWN start if none is open
  lost/expired   closes the open span; if none is open, produces a span with an unknown
  self_op        start that ends here — a run we can see the end of but not the beginning
  strike         evidence of PRESENCE. Never opens or closes a contract, but a strike
  violation      against Aramark at a venue in 2008 proves Aramark ran it in 2008, so it
  initiative     extends what we know and, with nothing open, starts an unknown-start span

Three distinctions this module refuses to collapse:

**`ongoing` is not `unknown`.** An open span means one of two opposite things: they still
hold it, or we never found the end. A span is called `ongoing` only when its most recent
evidence is inside `ONGOING_WINDOW_YEARS` of `as_of`; otherwise `unknown`. The map paints
`unknown` only as far as `known_through`, so a 1998 award with no follow-up does not
silently claim the venue for the next thirty years.

**Observed ends and inferred ends are different facts.** When another operator wins a venue
in 2011, the previous run did end — but no article said so. That span is closed with
`exit_mode="unknown"` and `extras.end_inferred_from = "succession"`, so a reviewer can tell
which end dates came from a sentence and which came from arithmetic. Without the
succession pass the map would show two operators holding one venue at the same time, which
is a different lie.

**A duplicate report is not a second event.** Three papers covering one award produce three
events; collapsing them is what keeps that from becoming three spans. All three event_ids
stay in `derived_from` — the provenance is the point.

    .venv/bin/python -m pipeline.spans.pair
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from ..schema import SPINE_TO_TENURE_TYPE, normalize_operator, validate_tenure

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
EVENTS = OUT / "contract_events.json"
SPINE = OUT / "venues_full.json"
TENURE = OUT / "tenure_records.json"

OPENERS = {"won"}
EXTENDERS = {"renewed"}
CLOSERS = {"lost", "expired", "self_op"}
PRESENCE = {"strike", "violation", "initiative"}

EXIT_MODE_FOR = {
    "lost": "lost_bid",
    "self_op": "self_op_conversion",
    # An expiry is a known ending with an unknown sequel — not a lost bid, not a
    # termination. `other` plus a note beats forcing it into a mode that implies a cause.
    "expired": "other",
}

# Two reports of the same award land within a few weeks of each other. Two real awards do
# not: concession contracts run five to fifteen years.
DUP_WINDOW_DAYS = 45

# Finer precision wins when collapsing duplicates — one paper says "March 2004", another
# says "March 3, 2004", and the second is the one to keep.
PRECISION_RANK = {"exact": 0, "month": 1, "year": 2, "approx": 3}

# How recent the last evidence must be before an open span is called `ongoing` rather than
# `unknown`. Three years is roughly the point past which silence stops meaning continuity.
ONGOING_WINDOW_YEARS = 3


def _date(v: Any) -> dt.date | None:
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _rank(ev: dict[str, Any]) -> int:
    return PRECISION_RANK.get(ev.get("date_precision") or "", 9)


def _venue_key(ev: dict[str, Any]) -> str:
    """What counts as "the same venue". `venue_id` when the spine matched; otherwise the
    printed name, lowercased — worse, but grouping by nothing would be worse still."""
    if ev.get("venue_id"):
        return ev["venue_id"]
    return "name:" + (ev.get("venue_name_as_written") or "").strip().lower()


def _review(span: dict[str, Any], reason: str) -> None:
    span["extras"]["needs_review"] = True
    if reason not in span["extras"]["review_reasons"]:
        span["extras"]["review_reasons"].append(reason)


# ── Step 1: one occurrence per real-world event ────────────────────────────────

def collapse_duplicates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold repeat coverage of one event into one occurrence, keeping every event_id.

    Same group, same `event_type`, dates within `DUP_WINDOW_DAYS`. The surviving record
    takes the most specific date available, not the first one seen.
    """
    dated = sorted((e for e in events if _date(e.get("event_date"))),
                   key=lambda e: (e["event_type"], str(e["event_date"])))
    undated = [e for e in events if not _date(e.get("event_date"))]

    out: list[dict[str, Any]] = []
    for ev in dated:
        prev = out[-1] if out else None
        if (prev and prev["event_type"] == ev["event_type"]
                and abs((_date(ev["event_date"]) - _date(prev["event_date"])).days) <= DUP_WINDOW_DAYS):
            prev["_event_ids"].append(ev.get("event_id"))
            prev["_sources"].append(ev)
            if _rank(ev) < _rank(prev):
                prev["event_date"] = ev["event_date"]
                prev["date_precision"] = ev.get("date_precision")
            continue
        merged = dict(ev)
        merged["_event_ids"] = [ev.get("event_id")]
        merged["_sources"] = [ev]
        out.append(merged)

    for ev in undated:
        merged = dict(ev)
        merged["_event_ids"] = [ev.get("event_id")]
        merged["_sources"] = [ev]
        out.append(merged)

    out.sort(key=lambda e: (str(e.get("event_date") or "9999"), e.get("event_type") or ""))
    return out


# ── Step 2: walk one operator's timeline at one venue ──────────────────────────

def _new_span(venue_key: str, operator: str) -> dict[str, Any]:
    return {
        "_venue_key": venue_key,
        "operator_normalized": operator,
        "start_date": None,
        "start_precision": None,
        "end_date": None,
        "end_precision": None,
        "end_status": "unknown",
        "exit_mode": None,
        "derived_from": [],
        "_events": [],
        "notes_parts": [],
        "extras": {"needs_review": False, "review_reasons": [], "known_through": None},
    }


def _absorb(span: dict[str, Any], ev: dict[str, Any]) -> None:
    span["derived_from"].extend(i for i in ev["_event_ids"] if i)
    span["_events"].append(ev)
    d = ev.get("event_date")
    if d and (span["extras"]["known_through"] or "") < str(d):
        span["extras"]["known_through"] = str(d)


def build_spans(events: list[dict[str, Any]], venue_key: str, operator: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    open_span: dict[str, Any] | None = None
    undated: list[dict[str, Any]] = []

    for ev in events:
        kind = ev.get("event_type")
        when = ev.get("event_date")

        if not when:
            # Real evidence with no place on the timeline. It cannot open or close
            # anything, but discarding it would drop a source from the provenance.
            undated.append(ev)
            continue

        if kind in OPENERS:
            if open_span is not None:
                # A second award with no reported loss in between is a re-award, not a
                # second simultaneous contract. Opening a new span here would make the
                # operator overlap itself.
                _absorb(open_span, ev)
                _review(open_span, "re-awarded with no reported end to the previous run")
                continue
            open_span = _new_span(venue_key, operator)
            open_span["start_date"] = when
            open_span["start_precision"] = ev.get("date_precision")
            _absorb(open_span, ev)
            spans.append(open_span)
            continue

        if kind in CLOSERS:
            # An institution taking food service in-house *starts* the self-operated run;
            # it ends whichever contractor was there, and that contractor is a different
            # group, so the succession pass handles the other side.
            if kind == "self_op" and operator == "Self-operated":
                if open_span is None:
                    open_span = _new_span(venue_key, operator)
                    open_span["start_date"] = when
                    open_span["start_precision"] = ev.get("date_precision")
                    spans.append(open_span)
                _absorb(open_span, ev)
                continue

            if open_span is None:
                open_span = _new_span(venue_key, operator)
                spans.append(open_span)
                _review(open_span, "run ends with no award ever reported — start unknown")
            _absorb(open_span, ev)
            open_span["end_date"] = when
            open_span["end_precision"] = ev.get("date_precision")
            open_span["end_status"] = "ended"
            open_span["exit_mode"] = EXIT_MODE_FOR.get(kind, "unknown")
            if kind == "expired":
                open_span["notes_parts"].append("contract expired; no cause reported")
            open_span = None
            continue

        if kind in EXTENDERS or kind in PRESENCE:
            if open_span is None:
                open_span = _new_span(venue_key, operator)
                spans.append(open_span)
                _review(open_span, (
                    "renewal with no award ever reported — start unknown"
                    if kind in EXTENDERS else
                    f"presence only ({kind}) — operator was here, but no award was reported"
                ))
            _absorb(open_span, ev)
            continue

        _absorb(open_span or _new_span(venue_key, operator), ev)

    if undated:
        target = spans[-1] if spans else None
        if target is None:
            target = _new_span(venue_key, operator)
            spans.append(target)
        for ev in undated:
            _absorb(target, ev)
        _review(target, f"{len(undated)} undated event(s) could not be placed on the timeline")

    for span in spans:
        if span["start_date"] is None:
            _review(span, "start_date unknown")
    return spans


# ── Step 3: what the other operators at this venue imply ───────────────────────

def _interval_end(span: dict[str, Any], as_of: dt.date) -> str:
    return span["end_date"] or span["extras"]["known_through"] or as_of.isoformat()


def resolve_venue_conflicts(spans: list[dict[str, Any]], as_of: dt.date) -> None:
    """Close open spans a later operator must have displaced, and flag true overlaps.

    A venue has one prime concessionaire at a time. When a different operator's run starts
    after this one and this one was never closed, the run did end — but no article said so,
    and the difference is recorded rather than smoothed over.
    """
    by_venue: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        by_venue.setdefault(span["_venue_key"], []).append(span)

    for venue_spans in by_venue.values():
        if len(venue_spans) < 2:
            continue
        for span in venue_spans:
            if span["end_status"] == "ended" or span["start_date"] is None:
                continue
            successors = [
                s for s in venue_spans
                if s is not span
                and s["operator_normalized"] != span["operator_normalized"]
                and s["start_date"] and s["start_date"] > span["start_date"]
            ]
            if not successors:
                continue
            nxt = min(successors, key=lambda s: s["start_date"])
            span["end_date"] = nxt["start_date"]
            span["end_precision"] = nxt["start_precision"]
            span["end_status"] = "ended"
            # We know *that* it ended, not *why* — `lost_bid` would be a guess. The one
            # exception is a successor that is the institution itself: that is not a guess
            # about the cause, it is the cause.
            span["exit_mode"] = ("self_op_conversion"
                                 if nxt["operator_normalized"] == "Self-operated"
                                 else "unknown")
            span["extras"]["end_inferred_from"] = "succession"
            span["extras"]["succeeded_by"] = nxt["operator_normalized"]
            span["notes_parts"].append(
                f"end date inferred from {nxt['operator_normalized']}'s run starting "
                f"{nxt['start_date']}; no article reported this run ending"
            )
            _review(span, "end inferred from succession, not reported")

        # Genuine simultaneity: a prime contractor and a premium-dining operator can both
        # be real, so this is flagged for a human rather than resolved by rule.
        # A span with no start and no dated evidence has no position on the timeline, so it
        # cannot be shown to overlap anything. Reporting it as overlapping every operator at
        # the venue would bury the real overlaps under noise.
        placed = [s for s in venue_spans if s["start_date"] or s["extras"]["known_through"]]
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if a["operator_normalized"] == b["operator_normalized"]:
                    continue
                a_start, b_start = a["start_date"] or "0000", b["start_date"] or "0000"
                a_end, b_end = _interval_end(a, as_of), _interval_end(b, as_of)
                if a_start < b_end and b_start < a_end:
                    for one, other in ((a, b), (b, a)):
                        one["extras"].setdefault("overlaps_with", [])
                        if other["operator_normalized"] not in one["extras"]["overlaps_with"]:
                            one["extras"]["overlaps_with"].append(other["operator_normalized"])
                        _review(one, "overlaps another operator at this venue "
                                     "(prime vs sub-contract, or a bad pairing)")


# ── Step 4: ongoing vs unknown, and the workbook-shaped output ─────────────────

def _finish_status(span: dict[str, Any], as_of: dt.date) -> None:
    if span["end_status"] == "ended":
        return
    last = _date(span["extras"]["known_through"])
    recent = last is not None and (as_of - last).days <= ONGOING_WINDOW_YEARS * 365
    span["end_status"] = "ongoing" if recent else "unknown"
    # Deliberately not flagged for review. An unknown end is the normal state of a
    # twenty-year corpus, not a decision anyone can make at a desk — flagging it would put
    # most of the table in the review queue and drown the rows that need a human. It is
    # already visible as `end_status` + `known_through`, and the thing it actually calls
    # for is another search, which is what the hunt log is for.


def _source_string(span: dict[str, Any]) -> str:
    seen, parts = set(), []
    for ev in span["_events"]:
        for src in ev["_sources"]:
            cite = f"{src.get('source_publication') or '?'} {src.get('source_date') or '?'}"
            if cite not in seen:
                seen.add(cite)
                parts.append(cite)
    return "; ".join(parts[:8]) or "unsourced"


def _tenure_id(span: dict[str, Any]) -> str:
    """Identity of a span, seeded on the events that built it.

    Was `venue|operator|start_date`, which collided: 67 of 102 spans have no known start,
    so every span for one operator at one venue hashed to the same id. On the real corpus
    that produced 95 ids for 102 rows — Drexel alone had two Sodexo runs sharing an id
    while reporting different exit modes (`contract expired` vs `lost the bid`), and the
    console dropped one of them because React de-duplicates by key.

    They are not duplicates and must not be merged: they rest on different articles. What
    was wrong was the identity, not the pairing. Seeding on the sorted event ids says the
    true thing — two spans built from different evidence are different spans, two built
    from the same evidence are the same one — and stays stable across re-runs because
    event ids are themselves content hashes.

    Venue and operator stay in the seed. They are implied by the events, but an id that
    changes when a *citation* is corrected and not when the *venue* is would be confusing
    to debug, and the cost of pinning them is nothing.
    """
    events = "|".join(sorted(ev.get("event_id") or "" for ev in span["_events"]))
    seed = f"{span['_venue_key']}|{span['operator_normalized']}|{events}"
    return "sp-" + hashlib.sha256(seed.encode()).hexdigest()[:10]


def _finalize(span: dict[str, Any], venues: dict[str, dict[str, Any]]) -> dict[str, Any]:
    first = span["_events"][0] if span["_events"] else {}
    venue = venues.get(span["_venue_key"])

    row = {
        "tenure_id": _tenure_id(span),
        "venue_id": venue["venue_id"] if venue else None,
        "venue_name": (venue or {}).get("canonical_name")
                      or first.get("venue_name_as_written") or "unknown venue",
        "venue_type": SPINE_TO_TENURE_TYPE.get((venue or {}).get("venue_type") or "", "other"),
        "city": (venue or {}).get("city"),
        "state": (venue or {}).get("state"),
        "lat": (venue or {}).get("lat"),
        "lng": (venue or {}).get("lng"),
        # `operator` is "as commonly known today", which is what the crosswalk resolves to.
        "operator": span["operator_normalized"],
        "operator_normalized": span["operator_normalized"],
        "start_date": span["start_date"],
        "start_precision": span["start_precision"],
        "end_date": span["end_date"],
        "end_precision": span["end_precision"],
        "end_status": span["end_status"],
        "exit_mode": span["exit_mode"],
        "derived_from": span["derived_from"],
        "source": _source_string(span),
        "notes": "; ".join(span["notes_parts"]) or None,
        "extras": span["extras"],
    }
    if not venue:
        _review(span, "venue never matched the spine — not mappable")
    row["extras"]["event_count"] = len(span["_events"])
    sub_brands = sorted({e.get("sub_brand") for e in span["_events"] if e.get("sub_brand")})
    if sub_brands:
        row["extras"]["sub_brands"] = sub_brands
    return row


# ── Orchestration ──────────────────────────────────────────────────────────────

def pair(events: list[dict[str, Any]], venues: dict[str, dict[str, Any]] | None = None,
         as_of: dt.date | None = None) -> dict[str, Any]:
    as_of = as_of or dt.date.today()
    venues = venues if venues is not None else load_venues()

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unusable: list[dict[str, Any]] = []
    for ev in events:
        operator = ev.get("operator_normalized") or normalize_operator(
            ev.get("operator"))["operator_normalized"]
        if not operator:
            unusable.append({"event_id": ev.get("event_id"), "why": "no operator"})
            continue
        if ev.get("event_type") not in OPENERS | EXTENDERS | CLOSERS | PRESENCE:
            unusable.append({"event_id": ev.get("event_id"),
                             "why": f"unknown event_type {ev.get('event_type')!r}"})
            continue
        groups.setdefault((_venue_key(ev), operator), []).append(ev)

    spans: list[dict[str, Any]] = []
    for (venue_key, operator), group in sorted(groups.items()):
        spans.extend(build_spans(collapse_duplicates(group), venue_key, operator))

    resolve_venue_conflicts(spans, as_of)
    for span in spans:
        _finish_status(span, as_of)

    rows = [_finalize(s, venues) for s in spans]
    problems = [p for row in rows for p in validate_tenure(row)]

    paired = sum(len(s["derived_from"]) for s in spans)
    return {
        "as_of": as_of.isoformat(),
        "tenure": rows,
        "problems": problems,
        "unusable_events": unusable,
        "stats": {
            "events_in": len(events),
            "events_paired": paired,
            "events_unusable": len(unusable),
            "events_unaccounted": len(events) - paired - len(unusable),
            "spans": len(rows),
            "ended": sum(1 for r in rows if r["end_status"] == "ended"),
            "ongoing": sum(1 for r in rows if r["end_status"] == "ongoing"),
            "unknown_end": sum(1 for r in rows if r["end_status"] == "unknown"),
            "unknown_start": sum(1 for r in rows if not r["start_date"]),
            "ends_inferred": sum(1 for r in rows if r["extras"].get("end_inferred_from")),
            "needs_review": sum(1 for r in rows if r["extras"].get("needs_review")),
            "unmapped": sum(1 for r in rows if not r["venue_id"]),
        },
    }


def load_venues() -> dict[str, dict[str, Any]]:
    if not SPINE.exists():
        return {}
    return {v["venue_id"]: v for v in json.loads(SPINE.read_text())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=Path, default=EVENTS)
    # Without this the pairer wrote the deliverable whichever events it was handed, so
    # running a fixture through it replaced the real tenure table with the fixture — which
    # is exactly what happened the first time the extraction runner's output was tried here.
    ap.add_argument("--out", type=Path, default=TENURE,
                    help="where to write spans (defaults to the real tenure table)")
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None,
                    help="treat this date as today (makes ongoing/unknown reproducible)")
    ap.add_argument("--show", type=int, default=0, help="print the first N spans")
    args = ap.parse_args()

    if not args.events.exists():
        raise SystemExit(
            f"no events to pair: {args.events} does not exist.\n"
            "  Extraction (pipeline.extract) has not been run — it is blocked on articles."
        )

    result = pair(json.loads(args.events.read_text()), as_of=args.as_of)
    args.out.write_text(json.dumps(result["tenure"], indent=2))
    s = result["stats"]

    print(f"\nPAIR {args.events.name} -> {args.out.name}   (as of {result['as_of']})")
    print(f"  events     {s['events_in']}  paired {s['events_paired']}  "
          f"unusable {s['events_unusable']}  unaccounted {s['events_unaccounted']}")
    print(f"  spans      {s['spans']}")
    print(f"    ended        {s['ended']}  ({s['ends_inferred']} of those inferred from succession)")
    print(f"    ongoing      {s['ongoing']}")
    print(f"    unknown end  {s['unknown_end']}")
    print(f"    unknown start {s['unknown_start']}")
    print(f"  needs review {s['needs_review']}  |  not mappable {s['unmapped']}")

    if s["events_unaccounted"]:
        print(f"\n  ! {s['events_unaccounted']} event(s) vanished between input and spans — "
              "every event must land in exactly one span or in unusable_events")
    if result["problems"]:
        print(f"\n  ! {len(result['problems'])} schema problem(s):")
        for p in result["problems"][:10]:
            print(f"      {p}")

    for row in result["tenure"][:args.show]:
        print(f"\n  {row['venue_name']} / {row['operator']}")
        print(f"    {row['start_date'] or '?'} -> {row['end_date'] or '?'}  "
              f"[{row['end_status']}{'/' + row['exit_mode'] if row['exit_mode'] else ''}]  "
              f"from {len(row['derived_from'])} event(s)")
        if row["extras"].get("review_reasons"):
            print(f"    review: {row['extras']['review_reasons']}")

    print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
