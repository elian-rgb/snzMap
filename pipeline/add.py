"""Put a folder of articles on the map with one command.

`ADDING_DATA.md` used to open by admitting there is no upload button, no Drive folder and
no web form — adding data is a developer task. That admission was honest but it named the
wrong barrier. Measured, the barrier was three things, and only two of them are removable:

  * **Sequencing.** collect -> ingest -> extract -> pair -> emit -> copy, six commands with
    four flags between them, where running them out of order does not error — it quietly
    publishes a map built from the previous run's events. Removable, and removed here.
  * **Publishing.** The geojson has to be copied into `console/public/data/` or the console
    keeps serving yesterday's file while every command above reports success. Removable.
  * **Money.** Extraction is the one stage that calls a paid API. The last full run cost
    $12.85 for 366 articles — about 3.5c each. **Not removable by any interface.**

So this collapses the six commands into one and refuses to hide the third thing. Running it
without `--spend` does every free stage, prints what the paid stage would cost against that
measured per-article rate, and stops with the exact command to continue. That stop is the
point of the design, not a limitation of it: a web form with an Upload button would put a
real charge behind a click that does not mention one, which is a worse artifact than a
command that names the number and waits.

A web form was considered and rejected on the same evidence. In production `console/server.ts`
serves a static `dist/`; extraction needs Python, the spine index and an `ANTHROPIC_API_KEY`
on the same host. A form would therefore only work for somebody already running this repo
locally — somebody who can already run this command. It would have moved the button without
moving the barrier.

Re-running is safe and nearly free. `collect` skips files whose bytes it has already seen,
and extraction reads the response cache in `raw/extract/`, so a second run over the same
folder re-publishes without paying twice. That is what makes `--publish` alone worth having:
after editing anything by hand, it rebuilds spans, geojson and the console copies from the
events already on disk, with no API key involved at all.

    .venv/bin/python -m pipeline.add ~/Desktop/new-articles            # free stages + a quote
    .venv/bin/python -m pipeline.add ~/Desktop/new-articles --spend    # the whole thing
    .venv/bin/python -m pipeline.add --publish                         # rebuild the map, no spend
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .common.http import PoliteSession
from .emit.records import emit
from .extract.run import (
    EVENTS,
    PRICE_PER_MTOK,
    RATES_CHECKED,
    REJECTED,
    REPORT,
    article_key,
    build_payload,
)
from .extract.run import run as extract_run
from .extract.prompt import MODEL
from .ingest.collect import collect
from .ingest.run import run as ingest_run
from .spans.pair import TENURE, pair

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
ARTICLES = OUT / "articles.json"
CONSOLE_DATA = ROOT.parent / "console" / "public" / "data"

# Copied into the console at the end — and *only* these two, which are the only files the
# emit stage above actually rewrites.
#
# The first draft published every layer in `output/`, on the theory that refreshing more is
# safer than refreshing less. It is not. `output/federal_venue_awards.geojson` was three days
# older than the copy the console was already serving, so adding a single article would have
# silently rolled the federal layer back to a stale version — an unrelated layer degraded by
# a command nobody pointed at it. The spine and the ACS and federal layers come from
# pipelines this command does not run, so it has no newer version of them to offer and no
# business touching them.
#
# `audit_summary.json` is excluded for a different reason: it is deliberately stale. It
# describes an audit of the *previous* extraction, and copying it forward after new articles
# land would attach an old precision figure to a corpus it was never measured on. The
# console keeps showing the last real audit until somebody runs a new one.
PUBLISH = ["tenure_records.geojson", "contract_events.geojson"]


def _rule(title: str) -> None:
    print(f"\n{'─' * 72}\n{title}\n{'─' * 72}")


def default_label() -> str:
    return "add-" + dt.date.today().isoformat()


def safe_label(label: str) -> str:
    """Labels become a directory name under `articles/raw/`, and `source_file` in every
    event is built from that path. A label with a slash in it would silently write outside
    the folder it claims to be in and break the promise that `source_file` points at a real
    file somebody can open."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    if not clean:
        raise SystemExit(f"--label {label!r} has no usable characters")
    return clean


# ── Cost ───────────────────────────────────────────────────────────────────────

def usd(u: dict[str, int]) -> float:
    p = PRICE_PER_MTOK
    return (u.get("input_tokens", 0) * p["input"]
            + u.get("output_tokens", 0) * p["output"]
            + u.get("cache_creation_input_tokens", 0) * p["cache_write"]
            + u.get("cache_read_input_tokens", 0) * p["cache_read"]) / 1_000_000


def measured_rate() -> tuple[float, int] | None:
    """Dollars per article from the last real extraction, or None if there has not been one.

    Preferred over an input-token estimate because it includes output tokens, which are 5x
    the price and cannot be estimated before the model answers. An estimate that quietly
    omits the expensive half of the bill is not a quote.
    """
    if not REPORT.exists():
        return None
    try:
        d = json.loads(REPORT.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    u, n = d.get("usage") or {}, len([a for a in d.get("per_article", []) if not a.get("error")])
    if not n or not u.get("input_tokens"):
        return None
    return usd(u) / n, n


def uncached(articles: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """Articles that would actually cost money — the rest are already in `raw/extract/`.

    This builds the same payload `extract.run` will build and asks the session where its
    response would be cached. Deriving the hash independently here would drift from the
    real one and quote for work that is already paid for.
    """
    session = PoliteSession("extract")  # constructed for path resolution; makes no request
    from .extract.candidates import build_index, find_for_article

    index = build_index()
    out = []
    for a in articles:
        payload = build_payload(a, find_for_article(a, index), model)
        if not session.cache_path_for(payload, article_key(a)).exists():
            out.append(a)
    return out


# ── Stages ─────────────────────────────────────────────────────────────────────

def stage_collect(source: Path, label: str) -> dict[str, Any]:
    _rule(f"1/5  COLLECT   {source}  ->  articles/raw/{label}/")
    m = collect(source, label)
    print(f"  copied      {len(m['copied'])} file(s)")
    print(f"  duplicates  {len(m['duplicates'])}  (identical bytes, skipped)")
    print(f"  skipped     {len(m['skipped'])}  (not an article format)")
    for s in m["skipped"][:5]:
        print(f"    - {s['path']}  ({s['reason']})")
    if len(m["skipped"]) > 5:
        print(f"    ... {len(m['skipped']) - 5} more — see output/ingest_manifest_{label}.json")
    if not m["copied"]:
        print("\n  Nothing was copied. Either the folder holds no .txt/.html/.rtf/.pdf/.docx\n"
              "  files, or every file in it is already in the corpus.")
    return m


def stage_ingest() -> dict[str, Any]:
    _rule("2/5  PARSE     articles/raw/  ->  output/articles.json")
    r = ingest_run()
    ARTICLES.write_text(json.dumps(r["articles"], indent=2))
    cov = r["coverage"]
    print(f"  files       {r['files_seen']}  ({len(r['files_unreadable'])} unreadable)")
    print(f"  articles    {len(r['articles'])}")
    print(f"  usable      {r['usable']}  (has provenance + a non-empty body)")
    print(f"  text kept   {cov['text_retained']:.1%}   body share {cov['body_share']:.1%}")
    for u in r["files_unreadable"][:5]:
        print(f"    ! {u['source_file']}: {u['error']}")
    return r


def quote(articles: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    _rule("3/5  COST      what the paid stage would charge")
    withtext = [a for a in articles if a.get("body_text")]
    todo = uncached(withtext, model)
    rate = measured_rate()

    print(f"  articles         {len(articles)}  ({len(articles) - len(withtext)} have no body "
          f"text — page scans, never sent)")
    print(f"  already paid for {len(withtext) - len(todo)}  (cached in raw/extract/, free to redo)")
    print(f"  would be billed  {len(todo)}")

    if not todo:
        print("\n  Nothing new to extract. This run is free.")
        return todo
    if rate is None:
        print("\n  No previous run to price against, so there is no honest per-article rate\n"
              "  to quote yet. Run with --limit-style caution: extract a handful first.")
        return todo

    per, n = rate
    est = per * len(todo)
    print(f"\n  ~${est:,.2f}   ({len(todo)} x ${per:.4f}/article, measured over the last "
          f"{n}-article run)")
    print(f"  Rates last checked {RATES_CHECKED} — see PRICE_PER_MTOK in extract/run.py.")
    print("  An estimate, not a bill: cost scales with article length and how much the model finds.")
    return todo


def stage_extract(articles: list[dict[str, Any]], model: str) -> dict[str, Any]:
    _rule("3/5  EXTRACT   articles.json  ->  output/contract_events.json")
    withtext = [a for a in articles if a.get("body_text")]
    r = extract_run(withtext, session=PoliteSession("extract", min_interval_s=0.25), model=model)
    EVENTS.write_text(json.dumps(r["events"], indent=2))
    REJECTED.write_text(json.dumps(r["rejected"], indent=2))
    REPORT.write_text(json.dumps(
        {k: v for k, v in r.items() if k not in ("events", "rejected")}, indent=2))

    # Billed cost is summed over the articles that actually went to the API, NOT over
    # `r["usage"]`. That total includes the token counts read back out of cached responses,
    # so quoting it says this run cost whatever the original run cost: the first version of
    # this line reported "$12.88" for a run that billed a single article. A cost figure that
    # is 445x the real one is worse than no cost figure, and it fails in the direction that
    # scares somebody out of adding data.
    failed = [a for a in r["per_article"] if a.get("error")]
    billed = [a for a in r["per_article"] if not a.get("cached") and not a.get("error")]
    print(f"  events      {len(r['events'])} valid, {len(r['rejected'])} rejected")
    print(f"  calls failed {len(failed)}")
    print(f"  cache hits  {r['cache_hits']}/{len(withtext)}  (paid for on an earlier run, free here)")
    print(f"  billed      {len(billed)} article(s), ${sum(usd(a.get('usage') or {}) for a in billed):.4f} "
          f"at the {RATES_CHECKED} rates")
    for a in failed[:5]:
        print(f"    ! {a['source_file']}@{a['source_offset']}: {a['error']}")
    return r


def stage_pair(as_of: dt.date | None) -> dict[str, Any]:
    _rule("4/5  PAIR      contract_events.json  ->  output/tenure_records.json")
    if not EVENTS.exists():
        raise SystemExit(
            f"no events to pair: {EVENTS.name} does not exist.\n"
            "  Nothing has been extracted yet — run this command with --spend first.")
    result = pair(json.loads(EVENTS.read_text()), as_of=as_of)
    TENURE.write_text(json.dumps(result["tenure"], indent=2))
    s = result["stats"]
    print(f"  events      {s['events_in']}  paired {s['events_paired']}  "
          f"unusable {s['events_unusable']}")
    print(f"  runs        {s['spans']}  ({s['ended']} ended, {s['ongoing']} ongoing, "
          f"{s['unknown_end']} unknown)")
    print(f"  not mappable {s['unmapped']}  (no spine venue — in the CSV, off the map)")
    return result


def stage_emit_and_publish(as_of: dt.date | None) -> dict[str, Any]:
    _rule("5/5  EMIT      -> geojson + csv, then copy into the console")
    r = emit(as_of)
    t, e, q = r["tenure"], r["events"], r["review_queue"]
    print(f"  runs         {t['rows']} rows -> {t['features']} map features")
    print(f"  events       {e['rows']} rows, {e['mapped_events']} name a spine venue "
          f"({e['no_coordinates']} do not)")
    print(f"               -> {e['features']} map features, one per distinct claim"
          + (f" ({e['restatements']} restated by another article)" if e["restatements"] else ""))
    print(f"  review queue {q['rows']} rows, {q['actionable']} of them need a person "
          f"-> output/review_queue.csv")
    for cat, n in q["by_category"].items():
        if cat != "needs_a_person":
            print(f"                 {n:>4} {cat} — not a reviewer's to fix")

    CONSOLE_DATA.mkdir(parents=True, exist_ok=True)
    for name in PUBLISH:
        shutil.copy2(OUT / name, CONSOLE_DATA / name)
    print(f"\n  published -> console/public/data/: {', '.join(PUBLISH)}")
    # Said out loud rather than left implicit. Somebody who just added articles and sees the
    # federal or ACS layer unchanged should know that was the intent, not a failed copy.
    print("  untouched: venues, federal, ACS and the audit figure — this command does not "
          "produce them")
    return r


# ── Entry point ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.add",
        description="Put a folder of articles on the map in one command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  .venv/bin/python -m pipeline.add ~/Desktop/new-articles   # free stages + a quote\n"
               "  .venv/bin/python -m pipeline.add ~/Desktop/new-articles --spend\n"
               "  .venv/bin/python -m pipeline.add --publish                # rebuild, no spend\n",
    )
    ap.add_argument("source", nargs="?", type=Path,
                    help="folder of articles to add (.txt .html .rtf .pdf .docx)")
    ap.add_argument("--label", default=None,
                    help="subfolder under articles/raw/ (default: add-YYYY-MM-DD)")
    ap.add_argument("--spend", action="store_true",
                    help="actually call the extraction API — this costs money")
    ap.add_argument("--publish", action="store_true",
                    help="rebuild spans, geojson and the console copies from events already "
                         "on disk; makes no API call")
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=None,
                    help="treat this date as today (fixes how ongoing runs are painted)")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args(argv)

    if not args.source and not (args.publish or args.spend):
        ap.print_help()
        print("\nGive it a folder, or use --publish to rebuild the map from what is already here.")
        return 1

    if args.source:
        label = safe_label(args.label or default_label())
        if not args.source.exists():
            raise SystemExit(f"no such folder: {args.source}")
        if not args.source.is_dir():
            raise SystemExit(f"{args.source} is a file, not a folder — "
                             f"put it in a folder and pass that")
        stage_collect(args.source, label)
        stage_ingest()

    articles = json.loads(ARTICLES.read_text()) if ARTICLES.exists() else []

    if args.spend:
        if not articles:
            raise SystemExit("nothing to extract — output/articles.json is empty or missing")
        stage_extract(articles, args.model)
    elif not args.publish:
        todo = quote(articles, args.model)
        if todo:
            _rule("STOPPED — the next stage costs money")
            cmd = f"  .venv/bin/python -m pipeline.add {args.source} --spend"
            if args.label:
                cmd += f" --label {safe_label(args.label)}"
            print("Everything free has been done. The articles are collected and parsed;\n"
                  "nothing has been extracted, so the map has not changed yet.\n")
            print("To extract and publish, re-run with --spend:\n")
            print(cmd + "\n")
            print("You will need ANTHROPIC_API_KEY set:\n")
            print("  set -a; . ./.env; set +a\n")
            return 0
        print("\n  (nothing new to pay for — continuing to publish)")

    stage_pair(args.as_of)
    stage_emit_and_publish(args.as_of)

    _rule("DONE")
    print("The console is serving the new data. Reload it to see it.\n")
    print("Two things this command did NOT do, on purpose:\n")
    print("  * It did not check whether the new extractions are any good. Precision is\n"
          "    measured separately and the console prints whatever the last audit found:\n"
          "      .venv/bin/python -m pipeline.audit.sample --n 20\n"
          "      .venv/bin/python -m pipeline.audit.score --auditor \"your name\"\n"
          "      cp pipeline/output/audit_summary.json console/public/data/\n")
    print("  * It did not re-score recall against the gold set. If you added articles that\n"
          "    cover gold venues, re-run:  .venv/bin/python -m pipeline.spans.evaluate\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
