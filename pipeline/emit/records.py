"""Phase 1.7 — write what the map and the humans read.

Six files, three audiences:

    tenure_records.geojson    the map's primary layer — one point per operator's run
    tenure_records.csv        the same rows in Kiki's column order, paste-compatible
    contract_events.geojson   the intermediate layer, toggleable behind the tenure layer
    contract_events.csv       every extracted event, for auditing a span back to a sentence
    search_log.csv            searches performed, including the ones that found nothing
    review_queue.csv          everything the pipeline refused to decide by itself

Two things this module decides, because nothing upstream can:

**How far a span is painted.** `end_date` is only filled when a run is `ended`. An `ongoing`
run has no end date and neither does an `unknown` one — but they must not render the same
way. `render_end_year` comes from the span's status: an ended run stops at its end, an
ongoing run runs to now, and an `unknown` run stops at `known_through`, the last date any
article actually places the operator at the venue. `render_end_basis` says which of the
three it was, so a reader can tell a painted year that was reported from one that was
assumed. Without this the map's most common failure would be a 1998 award coloring a venue
through 2026.

**What is not on the map.** A span whose venue never matched the spine has no coordinates
and cannot be a feature. It is still a real run, so it goes in the CSV and the count is
printed — a row missing from the map has to be visible somewhere or it is just lost.

    .venv/bin/python -m pipeline.emit.records
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from ..schema import (
    DERIVED_TENURE_FIELDS,
    EVENT_FIELDS,
    WORKBOOK_HUNT_COLUMNS,
    WORKBOOK_TENURE_COLUMNS,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

TENURE_IN = OUT / "tenure_records.json"
EVENTS_IN = OUT / "contract_events.json"
ARTICLES_IN = OUT / "articles.json"
SPINE_IN = OUT / "venues_full.json"

SNIPPET_CHARS = 260

# Columns for the review queue. One shape for all three record types so the file sorts and
# filters as a single sheet — a reviewer works down one issue at a time, not one file.
REVIEW_COLUMNS = [
    "issue", "record_type", "record_id", "venue_name", "operator",
    "what_the_pipeline_produced", "source", "snippet",
]


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text()) if path.exists() else []


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({
                k: json.dumps(v) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            })


# ── Tenure ─────────────────────────────────────────────────────────────────────

def render_window(row: dict[str, Any], as_of: dt.date) -> dict[str, Any]:
    """The years the time slider should paint, and why those years.

    `unknown` is the case that matters. The run did not end at `known_through` — that is
    just where the evidence stops. Painting past it would turn a gap in the reporting into
    a claim about the world, which is the exact substitution this project exists to avoid.
    """
    extras = row.get("extras") or {}
    status = row.get("end_status")
    if status == "ended":
        return {"render_end_year": _year(row.get("end_date")), "render_end_basis": "reported end"}
    if status == "ongoing":
        return {"render_end_year": as_of.year, "render_end_basis": "still held as of last coverage"}
    return {
        "render_end_year": _year(extras.get("known_through")),
        "render_end_basis": "evidence stops here; the end is unknown",
    }


def tenure_feature(row: dict[str, Any], as_of: dt.date) -> dict[str, Any]:
    extras = row.get("extras") or {}
    props = {
        "tenure_id": row["tenure_id"],
        "venue_id": row.get("venue_id"),
        "venue_name": row.get("venue_name"),
        "venue_type": row.get("venue_type"),
        "city": row.get("city"),
        "state": row.get("state"),
        "operator": row.get("operator"),
        "operator_normalized": row.get("operator_normalized"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "end_status": row.get("end_status"),
        "exit_mode": row.get("exit_mode"),
        # Numeric so the time slider is an integer comparison, not a string one.
        "start_year": _year(row.get("start_date")),
        **render_window(row, as_of),
        "start_is_known": bool(row.get("start_date")),
        "end_inferred": bool(extras.get("end_inferred_from")),
        "needs_review": bool(extras.get("needs_review")),
        "event_count": extras.get("event_count", len(row.get("derived_from") or [])),
        "source": row.get("source"),
    }
    return {
        "type": "Feature",
        "id": row["tenure_id"],
        "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
        "properties": props,
    }


def emit_tenure(rows: list[dict[str, Any]], as_of: dt.date) -> dict[str, Any]:
    mappable = [r for r in rows if r.get("lat") is not None and r.get("lng") is not None]
    features = [tenure_feature(r, as_of) for r in mappable]
    (OUT / "tenure_records.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}))

    csv_rows = []
    for r in rows:
        extras = r.get("extras") or {}
        csv_rows.append({
            **r,
            "derived_from": " ".join(r.get("derived_from") or []),
            **render_window(r, as_of),
            "needs_review": bool(extras.get("needs_review")),
            "review_reasons": "; ".join(extras.get("review_reasons") or []),
            "known_through": extras.get("known_through"),
            "end_inferred_from": extras.get("end_inferred_from"),
        })
    columns = WORKBOOK_TENURE_COLUMNS + DERIVED_TENURE_FIELDS + [
        "known_through", "render_end_year", "render_end_basis",
        "end_inferred_from", "needs_review", "review_reasons",
    ]
    _write_csv(OUT / "tenure_records.csv", columns, csv_rows)

    # A run with no start date cannot satisfy `start_year <= T`, so it never paints. That
    # is correct — but it has to be counted, or the map quietly under-reports.
    return {
        "rows": len(rows),
        "features": len(features),
        "no_coordinates": len(rows) - len(mappable),
        "unpaintable_no_start": sum(1 for f in features
                                    if f["properties"]["start_year"] is None),
        "unpaintable_no_end": sum(1 for f in features
                                  if f["properties"]["render_end_year"] is None),
    }


# ── Events ─────────────────────────────────────────────────────────────────────

def emit_events(events: list[dict[str, Any]], venues: dict[str, dict[str, Any]]) -> dict[str, Any]:
    features = []
    for ev in events:
        venue = venues.get(ev.get("venue_id") or "")
        if not venue or venue.get("lat") is None:
            continue
        features.append({
            "type": "Feature",
            "id": ev.get("event_id"),
            "geometry": {"type": "Point", "coordinates": [venue["lng"], venue["lat"]]},
            "properties": {
                "event_id": ev.get("event_id"),
                "venue_id": ev.get("venue_id"),
                "venue_name": venue.get("canonical_name"),
                # Kept beside the canonical name on purpose: the printed name is what dates
                # the article, and disagreement between the two is worth seeing on the map.
                "venue_name_as_written": ev.get("venue_name_as_written"),
                "operator": ev.get("operator"),
                "operator_normalized": ev.get("operator_normalized"),
                "sub_brand": ev.get("sub_brand"),
                "event_type": ev.get("event_type"),
                "event_date": ev.get("event_date"),
                "event_year": _year(ev.get("event_date")),
                "date_precision": ev.get("date_precision"),
                "contract_value_usd": ev.get("contract_value_usd"),
                "extraction_confidence": ev.get("extraction_confidence"),
                "needs_review": bool(ev.get("needs_review")),
                "source_publication": ev.get("source_publication"),
                "source_date": ev.get("source_date"),
                "source_title": ev.get("source_title"),
                "source_file": ev.get("source_file"),
            },
        })
    (OUT / "contract_events.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}))

    _write_csv(OUT / "contract_events.csv", [f[0] for f in EVENT_FIELDS], events)
    return {"rows": len(events), "features": len(features),
            "no_coordinates": len(events) - len(features)}


# ── Search log ─────────────────────────────────────────────────────────────────

def emit_search_log() -> dict[str, Any]:
    """Kiki's hunt log, verbatim. `nothing_found` is the whole reason this file exists —
    a documented silence is interpretable, an empty cell is not."""
    try:
        from ..spans.gold import load_gold
        hunt = [h["record"] for h in load_gold()["hunt"]]
    except Exception as exc:
        return {"rows": 0, "error": f"{type(exc).__name__}: {exc}"}

    _write_csv(OUT / "search_log.csv", WORKBOOK_HUNT_COLUMNS + ["search_id"], hunt)
    return {
        "rows": len(hunt),
        "nothing_found": sum(1 for h in hunt if h.get("result") == "nothing_found"),
        "error": None,
    }


# ── Review queue ───────────────────────────────────────────────────────────────

def _article_index(articles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for a in articles:
        index.setdefault(a.get("source_file") or "", []).append(a)
    return index


def snippet_for(ev: dict[str, Any], index: dict[str, list[dict[str, Any]]]) -> str:
    """The sentence the reviewer needs, not the whole article.

    A review queue that makes someone open the source file to judge one row will not get
    used. The window is centred on the venue name as the article printed it.
    """
    candidates = index.get(ev.get("source_file") or "") or []
    article = next((a for a in candidates if a.get("source_title") == ev.get("source_title")),
                   candidates[0] if candidates else None)
    if not article:
        return ""
    body = " ".join((article.get("body_text") or "").split())
    needle = (ev.get("venue_name_as_written") or "").strip()
    at = body.lower().find(needle.lower()) if needle else -1
    if at < 0:
        return body[:SNIPPET_CHARS] + ("…" if len(body) > SNIPPET_CHARS else "")
    start = max(0, at - SNIPPET_CHARS // 3)
    end = start + SNIPPET_CHARS
    return ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")


def build_review_queue(
    tenure: list[dict[str, Any]],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = _article_index(articles)
    events_by_id = {e.get("event_id"): e for e in events}
    queue: list[dict[str, Any]] = []

    for row in tenure:
        extras = row.get("extras") or {}
        if not extras.get("needs_review"):
            continue
        first = next((events_by_id[i] for i in (row.get("derived_from") or [])
                      if i in events_by_id), None)
        span = (f"{row.get('start_date') or '?'} to {row.get('end_date') or '?'} "
                f"[{row.get('end_status')}"
                f"{'/' + row['exit_mode'] if row.get('exit_mode') else ''}]")
        for reason in extras.get("review_reasons") or ["flagged, reason not recorded"]:
            queue.append({
                "issue": reason,
                "record_type": "tenure",
                "record_id": row.get("tenure_id"),
                "venue_name": row.get("venue_name"),
                "operator": row.get("operator_normalized"),
                "what_the_pipeline_produced": span,
                "source": row.get("source"),
                "snippet": snippet_for(first, index) if first else "",
            })

    for ev in events:
        if not ev.get("needs_review"):
            continue
        queue.append({
            "issue": ev.get("notes") or "extraction flagged this event",
            "record_type": "event",
            "record_id": ev.get("event_id"),
            "venue_name": ev.get("venue_name_as_written"),
            "operator": ev.get("operator_normalized") or ev.get("operator"),
            "what_the_pipeline_produced":
                f"{ev.get('event_type')} on {ev.get('event_date') or '?'} "
                f"(confidence {ev.get('extraction_confidence')})",
            "source": f"{ev.get('source_publication')} {ev.get('source_date')}",
            "snippet": snippet_for(ev, index),
        })

    # An article the parser could not pin provenance on can yield no valid event at all, so
    # it is a hole in the corpus rather than a parsing curiosity. It belongs in front of a
    # person, next to everything else that needs one.
    for a in articles:
        for problem in a.get("problems") or []:
            queue.append({
                "issue": f"article unusable: {problem}",
                "record_type": "article",
                "record_id": f"{a.get('source_file')}@{a.get('source_offset')}",
                "venue_name": "",
                "operator": "",
                "what_the_pipeline_produced":
                    f"{a.get('source_publication') or '?'} / {a.get('source_date') or '?'} "
                    f"/ {a.get('source_title') or '?'}",
                "source": a.get("source_file"),
                "snippet": " ".join((a.get("body_text") or "").split())[:SNIPPET_CHARS],
            })

    # Grouped by issue, then venue: one sitting works through one class of problem at a
    # time, which is the difference between a monthly review and an abandoned spreadsheet.
    queue.sort(key=lambda r: (r["issue"], r["venue_name"] or "", r["record_id"] or ""))
    return queue


# ── Orchestration ──────────────────────────────────────────────────────────────

def emit(as_of: dt.date | None = None) -> dict[str, Any]:
    as_of = as_of or dt.date.today()
    OUT.mkdir(parents=True, exist_ok=True)

    tenure = _load(TENURE_IN)
    events = _load(EVENTS_IN)
    articles = _load(ARTICLES_IN)
    venues = {v["venue_id"]: v for v in _load(SPINE_IN)}

    queue = build_review_queue(tenure, events, articles)
    _write_csv(OUT / "review_queue.csv", REVIEW_COLUMNS, queue)

    by_issue: dict[str, int] = {}
    for r in queue:
        by_issue[r["issue"]] = by_issue.get(r["issue"], 0) + 1

    return {
        "as_of": as_of.isoformat(),
        "tenure": emit_tenure(tenure, as_of),
        "events": emit_events(events, venues),
        "search_log": emit_search_log(),
        "review_queue": {"rows": len(queue), "by_issue": by_issue},
        "missing_inputs": [p.name for p in (TENURE_IN, EVENTS_IN, ARTICLES_IN)
                           if not p.exists()],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None,
                    help="treat this date as today (fixes how `ongoing` spans are painted)")
    args = ap.parse_args()

    r = emit(args.as_of)
    t, e, s, q = r["tenure"], r["events"], r["search_log"], r["review_queue"]

    print(f"\nEMIT (as of {r['as_of']})")
    print(f"  tenure_records   {t['rows']} rows -> {t['features']} map features")
    if t["no_coordinates"]:
        print(f"    {t['no_coordinates']} run(s) have no coordinates — in the CSV, not on the map")
    if t["unpaintable_no_start"]:
        print(f"    {t['unpaintable_no_start']} feature(s) have no start year and will never paint")
    if t["unpaintable_no_end"]:
        print(f"    {t['unpaintable_no_end']} feature(s) have no evidence date and will never paint")
    print(f"  contract_events  {e['rows']} rows -> {e['features']} map features "
          f"({e['no_coordinates']} unmapped)")
    if s.get("error"):
        print(f"  search_log       skipped: {s['error']}")
    else:
        print(f"  search_log       {s['rows']} searches "
              f"({s.get('nothing_found', 0)} found nothing — that is data)")
    print(f"  review_queue     {q['rows']} rows")
    for issue, n in sorted(q["by_issue"].items(), key=lambda x: -x[1])[:8]:
        print(f"    {n:>4}  {issue}")

    if r["missing_inputs"]:
        print(f"\n  ! nothing upstream yet: {', '.join(r['missing_inputs'])} missing — "
              "the files below are shaped correctly but empty")

    print("\n  wrote tenure_records.{geojson,csv}, contract_events.{geojson,csv}, "
          "search_log.csv, review_queue.csv")
    print("  copy to the console with:  cp pipeline/output/*.geojson console/public/data/")


if __name__ == "__main__":
    main()
