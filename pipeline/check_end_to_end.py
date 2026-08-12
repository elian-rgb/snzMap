"""Dress rehearsal — drive a synthetic USB through every stage and count the rows at each hop.

Every stage has its own gate. Nothing until now has run all of them in sequence, which is
where a different class of bug lives: not "does this function work" but "does the file this
one writes match the file the next one reads". `pipeline/emit/` in particular has never
processed a single row — every file it has produced so far is empty — and it is the stage
that decides what the console actually renders.

    collect -> parse -> extract -> pair -> emit -> map features

The corpus is `fixtures/usb/`: a fake USB stick with the layouts a real export actually has
(Nexis classic, ProQuest, an HTML clipping), plus the things that go wrong on a real one —
a duplicate re-save, a `.doc` nobody can read, an article with no headline, an article with
no date. It is checked in, so the ingest numbers in the README are reproducible by anyone.

**What is real here and what is not.** Collect, parse, pair and emit run unmodified: real
files, real code, real output. Extraction is the exception — there is no API key here, so
the model's *answer* is a fixture (`ANSWERS` below), seeded into `PoliteSession`'s cache the
way `extract/check_run.py` does it. Everything around the call is real: real prompt, real
candidate finder, real repairs, real validation. This rehearsal proves the plumbing, not the
model.

**Safety.** The whole run is redirected into `_rehearsal/` by rebinding module constants,
which is exactly the kind of thing that silently half-works — miss one constant and the run
overwrites a deliverable. So every file under `output/` and `articles/` is hashed before the
run and re-hashed after, and a single changed byte fails the check. That guard is not
theoretical: `spans/pair.py` really did overwrite `tenure_records.json` once.

    .venv/bin/python -m pipeline.check_end_to_end
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .common.http import PoliteSession
from .emit import records as emit_mod
from .extract import run as extract_mod
from .extract.candidates import build_index, find_for_article
from .ingest import collect as collect_mod
from .ingest import run as ingest_mod
from .schema import validate_event
from .spans import pair as pair_mod

ROOT = Path(__file__).resolve().parent
USB = ROOT / "fixtures" / "usb"
SANDBOX = ROOT / "_rehearsal"
LABEL = "usb_fixture"
SESSION_NAME = "rehearsal"

# Pinned, because `ongoing` vs `unknown` is measured against today and an unpinned run would
# start failing on its own three years after the last fixture article.
AS_OF = dt.date(2026, 8, 11)

# Hashed before and after. Directories, walked recursively.
GUARDED = ("output", "articles")


# ── What the model "returns" ───────────────────────────────────────────────────

def _event(**over: Any) -> dict[str, Any]:
    base = {
        "operator": None, "operator_normalized": None, "sub_brand": None,
        "venue": None, "institution": None, "venue_name_as_written": None,
        "event_type": None, "event_date": None, "date_precision": "exact",
        "first_outsourcing": None, "contract_value_usd": None,
        "contract_length_years": None, "losing_bidders": None,
        "extraction_confidence": 0.9, "needs_review": False, "notes": None, "extras": None,
    }
    base.update(over)
    return base


# Matched to an article by a substring of its body, not by offset — editing a fixture file
# shifts every offset below it, and a key that breaks on an unrelated edit is a key that
# gets deleted rather than fixed.
ANSWERS: list[tuple[str, list[dict[str, Any]]]] = [
    ("Cardinals said Tuesday that Aramark", [
        _event(operator="Aramark Corp.", operator_normalized="Aramark",
               venue="Busch Stadium", venue_name_as_written="Busch Stadium",
               event_type="won", event_date="2005-11-01",
               contract_value_usd=30000000, contract_length_years=10,
               losing_bidders=["Levy Restaurants", "Centerplate"],
               extraction_confidence=0.95),
        _event(operator="Sportservice", operator_normalized="Delaware North",
               sub_brand="Sportservice",
               venue="Busch Stadium", venue_name_as_written="Busch Stadium",
               event_type="lost", event_date="2005-11-01",
               extraction_confidence=0.8,
               notes="the article reports the end of the run, not a bid it lost"),
    ]),
    # No headline survives the parse of this one, so `source_title` is null and every event
    # it produces must be rejected by the schema. That is the point of including it.
    ("concession workers at Coors Field walked off", [
        _event(operator="Aramark", operator_normalized="Aramark",
               venue="Coors Field", venue_name_as_written="Coors Field",
               event_type="strike", event_date="2011-04-17",
               extraction_confidence=0.85),
    ]),
    # Names a ballpark but reports no contract event. Zero is the correct answer.
    ("vendors were named this week", []),
    ("Sportservice unit will take over", [
        _event(operator="Sportservice", operator_normalized="Delaware North",
               sub_brand="Sportservice",
               venue="Busch Stadium", venue_name_as_written="Busch Stadium",
               event_type="won", event_date="2019-03-01", date_precision="month",
               extraction_confidence=0.9),
    ]),
    # A college dining hall: real contract, no spine venue. The span must survive into the
    # CSV without coordinates rather than disappearing because it cannot be drawn.
    ("ratified their first contract with", [
        _event(operator="Compass Group", operator_normalized="Compass Group",
               venue=None, venue_name_as_written="Whitmore College",
               institution="Whitmore College",
               event_type="strike", event_date="2019-09-01", date_precision="month",
               contract_length_years=3, extraction_confidence=0.7,
               notes="contract ratified; the award itself was never reported"),
    ]),
    ("awarded the concessions contract at Petco Park", [
        _event(operator="Sodexo", operator_normalized="Sodexo",
               venue="Petco Park", venue_name_as_written="Petco Park",
               event_type="won", event_date="2024-06-10",
               contract_length_years=7, extraction_confidence=0.9),
    ]),
]


def answer_for(article: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fixture answer for one article, with `venue` resolved to a real candidate id."""
    body = article.get("body_text") or ""
    hits = [spec for needle, spec in ANSWERS if needle in body]
    if len(hits) != 1:
        raise SystemExit(
            f"ANSWERS matched {len(hits)} specs for {article.get('source_file')}"
            f"@{article.get('source_offset')} — the fixture corpus and this file have drifted")

    by_name = {c["canonical_name"]: c["venue_id"] for c in candidates}
    events = []
    for spec in hits[0]:
        ev = dict(spec)
        venue = ev.pop("venue")
        if venue and venue not in by_name:
            raise SystemExit(
                f"fixture answer names {venue!r} but the candidate finder did not offer it "
                f"for {article.get('source_title')!r} — offered: {sorted(by_name)}")
        ev["venue_id"] = by_name.get(venue) if venue else None
        for f in extract_mod.SOURCE_FIELDS:
            ev[f] = article.get(f)
        events.append(ev)
    return events


def seed_cache(session: PoliteSession, articles: list[dict[str, Any]]) -> None:
    index = build_index()
    for article in articles:
        candidates = find_for_article(article, index)
        payload = extract_mod.build_payload(article, candidates)
        body = json.dumps({
            "id": "msg_rehearsal", "type": "message", "role": "assistant",
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "tu_1", "name": extract_mod.TOOL_NAME,
                         "input": {"events": answer_for(article, candidates)}}],
            "usage": {"input_tokens": 3200, "output_tokens": 350,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })
        session.cache_path_for(payload, extract_mod.article_key(article)).write_text(body)


# ── The guard ──────────────────────────────────────────────────────────────────

def fingerprint() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in GUARDED:
        base = ROOT / name
        for path in sorted(base.rglob("*")) if base.exists() else []:
            if path.is_file():
                out[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def diff_fingerprints(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = [f"MODIFIED {k}" for k in before if k in after and before[k] != after[k]]
    changed += [f"DELETED  {k}" for k in before if k not in after]
    changed += [f"CREATED  {k}" for k in after if k not in before]
    return sorted(changed)


# ── Redirection ────────────────────────────────────────────────────────────────

def redirect() -> dict[str, Path]:
    """Point every writing module at the sandbox.

    `collect` derives `source_file` with `dest.relative_to(ROOT)`, so the sandbox has to live
    under `pipeline/` — a `/tmp` directory raises instead. That constraint is why the guard
    above exists: the sandbox is a sibling of the real data, not somewhere it cannot reach.
    """
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    raw, out = SANDBOX / "raw", SANDBOX / "output"
    raw.mkdir(parents=True)
    out.mkdir(parents=True)

    collect_mod.RAW, collect_mod.OUT = raw, out
    ingest_mod.RAW, ingest_mod.OUT = raw, out
    # `emit.records` reads its inputs and writes its six outputs through module globals.
    # SPINE_IN is deliberately left pointing at the real spine: it is a read-only input, and
    # a rehearsal against a fake spine would prove nothing about what the map will draw.
    emit_mod.OUT = out
    emit_mod.TENURE_IN = out / "tenure_records.json"
    emit_mod.EVENTS_IN = out / "contract_events.json"
    emit_mod.ARTICLES_IN = out / "articles.json"
    return {"raw": raw, "out": out}


# ── The run ────────────────────────────────────────────────────────────────────

def main() -> int:
    if not USB.exists():
        raise SystemExit(f"no fixture corpus at {USB}")

    before = fingerprint()
    changed: list[str] = []
    try:
        code = rehearse()
    finally:
        # The guard has to survive a crash. Sabotaging `redirect()` to test it proved why:
        # emit wrote its six files into the real `output/` and *then* the run died two lines
        # later, so the check that would have reported the damage never ran. A stage that
        # fails halfway is exactly when a stray write is most likely and least expected.
        changed = diff_fingerprints(before, fingerprint())
        if changed:
            print(f"\n!! the rehearsal wrote to {len(changed)} real file(s) — "
                  f"a redirection in redirect() is missing or wrong:")
            for c in changed:
                print(f"     {c}")
            print("   restore from git or re-run the stage that owns them.")
    return 1 if changed else code


def rehearse() -> int:  # noqa: C901 - a sequence of stages reads better in one place
    paths = redirect()
    raw, out = paths["raw"], paths["out"]

    failures: list[str] = []
    ran: list[str] = []

    def want(label: str, ok: bool) -> None:
        ran.append(label)
        if not ok:
            failures.append(label)

    # 1 ── collect
    manifest = collect_mod.collect(USB, LABEL)
    on_usb = [p for p in USB.rglob("*") if p.is_file() and p.name not in collect_mod.IGNORE_NAMES]
    copied, skipped, dupes = manifest["copied"], manifest["skipped"], manifest["duplicates"]
    print(f"\nCOLLECT  {len(on_usb)} files on the stick "
          f"-> {len(copied)} copied, {len(dupes)} duplicate, {len(skipped)} skipped")
    want("every file on the stick was copied, skipped or called a duplicate",
         len(copied) + len(skipped) + len(dupes) == len(on_usb))
    want("the re-saved export was caught by hash, not copied twice", len(dupes) == 1)
    want("the .doc was listed as skipped rather than ignored",
         any(s["path"].endswith(".doc") for s in skipped))
    want("volume noise (.DS_Store) is not in any list",
         not any(".DS_Store" in json.dumps(x) for x in (copied, skipped, dupes)))

    # 2 ── parse
    ing = ingest_mod.run(raw)
    articles = ing["articles"]
    (out / "articles.json").write_text(json.dumps(articles, indent=2))
    cov = ing["coverage"]
    print(f"PARSE    {ing['files_seen']} files -> {len(articles)} articles "
          f"({ing['usable']} usable)  text retained {cov['text_retained']:.1%}  "
          f"body share {cov['body_share']:.1%}")
    want("every copied file was read", ing["files_seen"] == len(copied))
    want("no file was unreadable", not ing["files_unreadable"])
    want("the splitter found every document in the corpus", len(articles) == 6)
    want("almost all source text landed inside an article", cov["text_retained"] > 0.90)
    want("the article with no headline was flagged, not filled in",
         any("no headline found" in a["problems"] for a in articles))
    want("the article with no date was flagged, not filled in",
         any("no publication date found" in a["problems"] for a in articles))

    # 3 ── extract (real code, fixture answers)
    session = PoliteSession(SESSION_NAME, min_interval_s=0.0)
    seed_cache(session, articles)
    ex = extract_mod.run(articles, session=session, progress_every=0)
    events, rejected = ex["events"], ex["rejected"]
    (out / "contract_events.json").write_text(json.dumps(events, indent=2))
    returned = sum(a.get("events", 0) for a in ex["per_article"])
    print(f"EXTRACT  {len(articles)} articles -> {returned} events returned "
          f"({len(events)} kept, {len(rejected)} rejected)  "
          f"cache hits {ex['cache_hits']}/{len(articles)}")
    want("no article errored", not any(a.get("error") for a in ex["per_article"]))
    want("every call was served from the seeded cache — nothing was spent",
         ex["cache_hits"] == len(articles))
    want("no event went missing between the answer and the files",
         len(events) + len(rejected) == returned)
    want("every kept event validates", all(not validate_event(e) for e in events))
    want("an article with no headline yields no valid event",
         len(rejected) == 1 and any("source_title" in p for p in rejected[0]["problems"]))
    want("a sub-brand kept its own name and resolved to its parent",
         any(e["sub_brand"] == "Sportservice" and e["operator_normalized"] == "Delaware North"
             for e in events))
    want("the college dining event has no venue_id and was not invented one",
         any(e["venue_name_as_written"] == "Whitmore College" and e["venue_id"] is None
             for e in events))

    # 4 ── pair
    pr = pair_mod.pair(events, as_of=AS_OF)
    tenure = pr["tenure"]
    (out / "tenure_records.json").write_text(json.dumps(tenure, indent=2))
    s = pr["stats"]
    print(f"PAIR     {s['events_in']} events -> {s['spans']} spans  "
          f"(paired {s['events_paired']}, unusable {s['events_unusable']}, "
          f"unaccounted {s['events_unaccounted']})")
    want("every event landed in a span or in unusable_events",
         s["events_unaccounted"] == 0)
    want("no span failed the tenure schema", not pr["problems"])
    want("the 2005 award and the 2019 award produced separate Busch runs",
         len([r for r in tenure if r["venue_name"] == "Busch Stadium"]) == 3)
    want("Aramark's Busch run was closed by succession, not by an article",
         any(r["operator_normalized"] == "Aramark"
             and r["extras"].get("end_inferred_from") == "succession"
             and r["end_date"] == "2019-03-01" for r in tenure))
    want("a 2024 award is still called ongoing in 2026",
         any(r["operator_normalized"] == "Sodexo" and r["end_status"] == "ongoing"
             for r in tenure))
    want("a run whose venue never matched the spine survived as a row",
         any(r["venue_id"] is None and r["venue_name"] == "Whitmore College"
             for r in tenure))

    # 5 ── emit
    em = emit_mod.emit(AS_OF)
    t, e, q = em["tenure"], em["events"], em["review_queue"]
    print(f"EMIT     {t['rows']} spans -> {t['features']} map features "
          f"({t['no_coordinates']} without coordinates); "
          f"{e['rows']} events -> {e['features']} features; "
          f"review queue {q['rows']}")
    want("emit read every span the pairer wrote", t["rows"] == len(tenure))
    want("every mappable span became a feature",
         t["features"] == sum(1 for r in tenure if r["lat"] is not None))
    want("the unmappable run is counted, not silently dropped", t["no_coordinates"] == 1)
    # A run that ends without an award ever being reported has no start year, so it can
    # never satisfy `start_year <= T` and is never drawn. That is the right answer — the
    # wrong one would be pinning it to the first year we happen to have evidence for. It has
    # to be *counted* though, or the map under-reports in silence. The console picks the
    # same feature up and says so in the venue panel (`undatable` in VenuePanel.tsx).
    want("the run with no start date is counted as unpaintable, not quietly absent",
         t["unpaintable_no_start"] == 1)
    want("no feature is unpaintable for want of an end year", not t["unpaintable_no_end"])
    want("both the unusable articles reached the review queue",
         sum(1 for r in _rows(out / "review_queue.csv") if r["record_type"] == "article") == 2)

    geo = json.loads((out / "tenure_records.geojson").read_text())
    props = [f["properties"] for f in geo["features"]]
    bases = {p["render_end_basis"] for p in props}
    print(f"         render_end_basis: {sorted(bases)}")
    want("the geojson is a FeatureCollection the console can load",
         geo["type"] == "FeatureCollection" and bool(geo["features"]))
    want("every feature carries the two fields the time slider filters on",
         all("start_year" in p and "render_end_year" in p for p in props))
    paintable = [p for p in props
                 if isinstance(p["start_year"], int) and isinstance(p["render_end_year"], int)]
    want("every paintable feature has a coherent year window",
         bool(paintable) and all(p["start_year"] <= p["render_end_year"] for p in paintable))
    # The console's own filter, run here so a change to either side shows up as a number
    # rather than as an empty map somebody notices later.
    visible = {y: sum(1 for p in paintable
                      if p["start_year"] <= y <= p["render_end_year"]) for y in (2004, 2010, 2026)}
    print(f"         features visible at 2004 / 2010 / 2026: "
          f"{visible[2004]} / {visible[2010]} / {visible[2026]}")
    want("the slider shows nothing before the first award and something after",
         visible[2004] == 0 and visible[2010] >= 1 and visible[2026] >= 1)
    want("every feature has real coordinates",
         all(len(f["geometry"]["coordinates"]) == 2
             and all(isinstance(c, float) for c in f["geometry"]["coordinates"])
             for f in geo["features"]))
    want("all three kinds of painted end are represented and labelled",
         bases == {"reported end", "still held as of last coverage",
                   "evidence stops here; the end is unknown"})
    want("a run painted to 2026 says it was assumed, not reported",
         all(p["render_end_basis"] != "reported end"
             for p in props if p["render_end_year"] == AS_OF.year))

    total = len(ran)
    print(f"\nend-to-end: {total - len(failures)}/{total} pass")
    for f in failures:
        print(f"  FAIL  {f}")
    if failures:
        return 1
    print(f"\nPASS — {len(on_usb)} files on a stick became {len(geo['features'])} things on a "
          f"map, and every row that did not make it is written down somewhere.")
    print(f"  artifacts: {SANDBOX.relative_to(ROOT.parent)}/output/")
    return 0


def _rows(path: Path) -> list[dict[str, str]]:
    import csv
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    sys.exit(main())
