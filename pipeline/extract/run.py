"""Run the extraction prompt over every parsed article: articles.json -> contract_events.json.

This is the only stage in the pipeline where the data is *generated* rather than fetched or
derived, so it is the only stage where a clean-looking output file can be entirely invented.
Everything here is built around that one fact:

  * **The model is never trusted about provenance or identity.** `source_*` is overwritten
    from the article record and `venue_id` is checked against the candidate list it was
    offered. Both are repairs the pipeline can make correctly, so it makes them and counts
    them — a rising `venue_id not offered` count is the earliest sign the prompt has drifted
    into inventing, and it is printed at the top of the gate rather than buried.
  * **`normalize_operator` wins.** The model is asked for `operator_normalized` because
    asking improves its reasoning about sub-brands, but `schema.py` is what decides. A 2005
    Centerplate contract stays Centerplate.
  * **A row that fails `validate_event` is written to `extract_rejected.json`, never dropped.**
    `contract_events.json` has to stay schema-clean because `spans.pair` reads it, but a
    dropped row is invisible and an invisible row is how a gap becomes a wrong answer.

Resumability is the payload-hash cache in `PoliteSession`, not bookkeeping here: an
interrupted run re-reads the calls it already paid for and spends only on the rest. Runs are
sequential on purpose. 500 articles is roughly two hours unattended, and the cache makes the
second run free, which is a better trade before a deadline than a concurrent runner whose
failure mode is a half-written output file.

    .venv/bin/python -m pipeline.extract.run --dry-run       # prompts + token estimate, no spend
    .venv/bin/python -m pipeline.extract.run --limit 5       # a real 5-article trial
    .venv/bin/python -m pipeline.extract.run                 # everything in articles.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from ..common.http import PoliteSession
from ..schema import normalize_operator, validate_event
from .candidates import build_index, find_for_article
from .prompt import MODEL, RESPONSE_SCHEMA, SYSTEM, build_messages, validate_extraction

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
ARTICLES = OUT / "articles.json"
EVENTS = OUT / "contract_events.json"
REJECTED = OUT / "extract_rejected.json"
REPORT = OUT / "extract_run.json"

# `ANTHROPIC_BASE_URL` is honored because some environments route the API through a gateway,
# and a hardcoded host silently ignores that and fails on auth instead of saying why.
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
ENDPOINT = BASE_URL.rstrip("/") + "/v1/messages"
API_VERSION = "2023-06-01"
TOOL_NAME = "report_events"
MAX_TOKENS = 8000

# Consecutive failures that mean "this is the setup, not the corpus". Three, because two
# genuinely unlucky articles in a row is plausible and three is not.
FATAL_STREAK = 3

# Printed next to the cost in the gate so a stale rate is visible rather than silently wrong.
# Dollars per million tokens. Verify against current pricing before quoting the number.
RATES_CHECKED = "2026-08"
PRICE_PER_MTOK = {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50}


# ── The request ────────────────────────────────────────────────────────────────

def article_key(article: dict[str, Any]) -> str:
    """Stable per-article id. Also the cache filename, so `raw/extract/` is browsable."""
    seed = f"{article.get('source_file')}|{article.get('source_offset')}"
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def build_payload(article: dict[str, Any], candidates: list[dict[str, Any]],
                  model: str = MODEL) -> dict[str, Any]:
    """`cache_control` sits on the system block and the tool schema because those two are
    identical across every article in the run — measured at ~2,970 tokens, which is the
    majority of a short article's prompt. They are the only cacheable parts; the candidate
    list changes per article and must not be marked."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"}}],
        "tools": [{"name": TOOL_NAME,
                   "description": "Report the contract events this article states as fact.",
                   "input_schema": RESPONSE_SCHEMA,
                   "cache_control": {"type": "ephemeral"}}],
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
        "messages": build_messages(article, candidates),
    }


def check_response(text: str) -> None:
    """Retryable failures. A body that parses but carries no usable tool call is the same
    class of problem as WDQS's truncated 200s: it will crash the caller much later, in a
    place that does not name the request that caused it, so it is caught at the edge."""
    resp = json.loads(text)
    if resp.get("type") == "error":
        raise ValueError(f"api error: {resp.get('error', {}).get('message')}")
    if resp.get("stop_reason") == "max_tokens":
        raise ValueError(f"truncated at max_tokens={MAX_TOKENS}; tool input is incomplete")
    blocks = [b for b in resp.get("content", [])
              if b.get("type") == "tool_use" and b.get("name") == TOOL_NAME]
    if not blocks:
        raise ValueError(f"no {TOOL_NAME} tool_use block (stop_reason={resp.get('stop_reason')})")
    if not isinstance(blocks[0].get("input", {}).get("events"), list):
        raise ValueError("tool input has no `events` list")


def events_of(resp: dict[str, Any]) -> list[dict[str, Any]]:
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and b.get("name") == TOOL_NAME:
            return b["input"]["events"]
    return []


# ── Turning an answer into a row ───────────────────────────────────────────────

SOURCE_FIELDS = ("source_publication", "source_date", "source_title", "source_file")


def finalize(ev: dict[str, Any], article: dict[str, Any],
             candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Apply the repairs the pipeline is entitled to make, and report each one.

    "Entitled" is doing real work in that sentence. Overwriting a source field is safe
    because the article record is the authority and the model was only ever asked to copy
    it. Nulling an off-list `venue_id` is safe because an id that was not offered cannot be
    right. Neither of those is a judgement call. Anything that *is* a judgement call — a
    date whose precision disagrees with its value, an operator the crosswalk does not know —
    is left exactly as the model returned it and flagged for a person.
    """
    repairs: list[str] = []
    ev = dict(ev)

    for f in SOURCE_FIELDS:
        if ev.get(f) != article.get(f):
            repairs.append(f"{f} rewritten by model, restored from article")
            ev[f] = article.get(f)

    allowed = {c["venue_id"] for c in candidates}
    if ev.get("venue_id") and ev["venue_id"] not in allowed:
        repairs.append(f"venue_id {ev['venue_id']!r} was not offered as a candidate, nulled")
        ev["venue_id"] = None
        ev["needs_review"] = True

    # schema.py decides the parent company, not the model. Recorded when they disagree
    # because a systematic disagreement means the crosswalk in the prompt has gone stale.
    norm = normalize_operator(ev.get("operator"))
    if norm["operator_normalized"] != ev.get("operator_normalized"):
        repairs.append(
            f"operator_normalized {ev.get('operator_normalized')!r} -> "
            f"{norm['operator_normalized']!r} ({norm['relation']})"
        )
        ev["operator_normalized"] = norm["operator_normalized"]
    if norm.get("sub_brand") and not ev.get("sub_brand"):
        ev["sub_brand"] = norm["sub_brand"]
    if norm.get("needs_review"):
        ev["needs_review"] = True

    ev["event_id"] = mint_event_id(article, ev)
    return ev, repairs


def mint_event_id(article: dict[str, Any], ev: dict[str, Any]) -> str:
    """`source_file + offset + operator + venue`, per EVENT_FIELDS. Deterministic, so a
    re-run produces the same ids and `derived_from` on a tenure span stays meaningful."""
    seed = "|".join(str(x) for x in (
        article.get("source_file"), article.get("source_offset"),
        ev.get("operator"), ev.get("venue_id"), ev.get("event_type"), ev.get("event_date"),
    ))
    return "ev_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


# ── The run ────────────────────────────────────────────────────────────────────

def run(articles: list[dict[str, Any]], *, session: PoliteSession | None,
        model: str = MODEL, use_cache: bool = True, progress_every: int = 25) -> dict[str, Any]:
    index = build_index()
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_article: list[dict[str, Any]] = []
    usage_total = {"input_tokens": 0, "output_tokens": 0,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    started = time.monotonic()

    # Resolved once. An API key is only needed for articles that are not already on disk,
    # so re-running a finished extraction to regenerate the outputs costs nothing and
    # requires no credentials — which is also what lets check_run.py drive this loop.
    headers = _auth_headers(required=False)
    cache_hits = 0
    consecutive_failures = 0

    for i, article in enumerate(articles, 1):
        candidates = find_for_article(article, index)
        payload = build_payload(article, candidates, model)
        key = article_key(article)
        rec: dict[str, Any] = {"article_key": key, "source_file": article.get("source_file"),
                               "source_offset": article.get("source_offset"),
                               "candidates": len(candidates)}

        if session is None:  # --dry-run: everything except the spend
            chars = len(SYSTEM) + len(payload["messages"][0]["content"])
            rec.update({"dry_run": True, "prompt_chars": chars, "est_input_tokens": chars // 4})
            per_article.append(rec)
            continue

        cached = use_cache and session.cache_path_for(payload, key).exists()
        cache_hits += bool(cached)
        if not cached and not headers:
            raise SystemExit(
                f"ANTHROPIC_API_KEY is not set, and article {i}/{len(articles)} "
                f"({article.get('source_file')}) has no cached response — "
                f"export the key, or use --dry-run")

        t0 = time.monotonic()
        try:
            body = session.post_json(ENDPOINT, payload=payload,
                                     headers=headers, label=key,
                                     validate=check_response, use_cache=use_cache)
        except Exception as exc:  # noqa: BLE001 — one bad article is a line in the report
            rec.update({"error": f"{type(exc).__name__}: {exc}"})
            per_article.append(rec)
            # A bad key or a wrong endpoint fails identically on all 500 articles, and
            # finding that out at the end of an overnight run is the worst outcome. Two
            # rules catch it, because one is not enough:
            #   * a 401/403/404 comes straight out of `raise_for_status` as an HTTPError
            #     and is unambiguous, so it stops immediately;
            #   * an unreachable host does NOT — PoliteSession catches the connection error
            #     into its retry loop and raises RuntimeError, which is the same type an
            #     article the model keeps truncating produces. Those are told apart by
            #     counting: one bad article is isolated, a broken config fails every one.
            consecutive_failures += 1
            if isinstance(exc, requests.RequestException):
                raise SystemExit(
                    f"stopping at article {i}/{len(articles)} — HTTP error, which means "
                    f"configuration rather than content:\n  {exc}")
            if consecutive_failures >= FATAL_STREAK:
                raise SystemExit(
                    f"stopping at article {i}/{len(articles)} — {consecutive_failures} in a "
                    f"row failed, so this is the endpoint or the key, not the articles:\n"
                    f"  {exc}")
            continue

        consecutive_failures = 0
        elapsed = time.monotonic() - t0
        resp = json.loads(body)
        usage = resp.get("usage", {})
        for k in usage_total:
            usage_total[k] += usage.get(k, 0) or 0

        raw_events = events_of(resp)
        problems = validate_extraction(raw_events, candidates, article)
        kept, repairs = 0, []
        for ev in raw_events:
            row, reps = finalize(ev, article, candidates)
            repairs += reps
            bad = validate_event(row)
            if bad:
                rejected.append({"article_key": key, "problems": bad, "event": row})
            else:
                events.append(row)
                kept += 1

        rec.update({"events": len(raw_events), "kept": kept,
                    "rejected": len(raw_events) - kept, "repairs": repairs,
                    "extraction_problems": problems, "seconds": round(elapsed, 2),
                    "cached": bool(cached), "usage": usage})
        per_article.append(rec)

        if progress_every and i % progress_every == 0:
            rate = (time.monotonic() - started) / i
            left = rate * (len(articles) - i)
            print(f"  {i}/{len(articles)}  {len(events)} events  "
                  f"{rate:.1f}s/article  ~{left/60:.0f} min left", flush=True)

    return {"events": events, "rejected": rejected, "per_article": per_article,
            "usage": usage_total, "cache_hits": cache_hits,
            "seconds": round(time.monotonic() - started, 1)}


def _auth_headers(required: bool = True) -> dict[str, str]:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        if required:
            raise SystemExit("ANTHROPIC_API_KEY is not set — export it, or use --dry-run")
        return {}
    return {"x-api-key": key, "anthropic-version": API_VERSION}


def cost(usage: dict[str, int]) -> float:
    p = PRICE_PER_MTOK
    return (usage["input_tokens"] * p["input"]
            + usage["output_tokens"] * p["output"]
            + usage["cache_creation_input_tokens"] * p["cache_write"]
            + usage["cache_read_input_tokens"] * p["cache_read"]) / 1_000_000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--articles", type=Path, default=ARTICLES)
    ap.add_argument("--limit", type=int, help="extract only the first N articles")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="build every prompt and report size; make no API call")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore cached responses and re-ask (costs money again)")
    ap.add_argument("--interval", type=float, default=0.25,
                    help="minimum seconds between API calls")
    args = ap.parse_args()

    if not args.articles.exists():
        raise SystemExit(f"no articles to extract: {args.articles} does not exist "
                         f"(run pipeline.ingest.collect then pipeline.ingest.run first)")
    articles = json.loads(args.articles.read_text())

    # Articles with no body are dropped before the limit is applied, not after. 236 of the
    # 600 real documents are page scans with nothing in them, and they are not evenly
    # spread — two of the first five. Left in, `--limit 5` would spend two of its five calls
    # asking a model what a contract in an empty string says, which is both wasted money and
    # an invitation to invent one. This is a filter on *the source having text*, not on
    # quality: an article with a body but a missing headline still goes, because the missing
    # headline is a fact about the export that the gate should keep reporting.
    empty = [a for a in articles if not a.get("body_text")]
    articles = [a for a in articles if a.get("body_text")]
    if args.limit:
        articles = articles[:args.limit]
    if not articles:
        raise SystemExit(f"{args.articles} parsed to zero articles with a body — nothing to "
                         f"extract ({len(empty)} had none)")

    session = None if args.dry_run else PoliteSession("extract", min_interval_s=args.interval)
    r = run(articles, session=session, model=args.model, use_cache=not args.refresh)

    print(f"\nEXTRACT {args.articles.name}  model={args.model}")
    print(f"  articles      {len(articles)}")
    if empty:
        print(f"  skipped       {len(empty)}  (no body text — page scans; see ingest report)")

    no_cand = sum(1 for a in r["per_article"] if not a["candidates"])
    print(f"  no candidates {no_cand}  (no spine venue named; venue_id must be null)")

    if args.dry_run:
        est = sum(a["est_input_tokens"] for a in r["per_article"])
        print(f"  est input     ~{est:,} tokens before caching "
              f"(~{est // len(articles):,}/article)")
        print("  dry run — no API call made, nothing written")
        return

    failed = [a for a in r["per_article"] if a.get("error")]
    kept, rej = len(r["events"]), len(r["rejected"])
    print(f"  calls failed  {len(failed)}")
    print(f"  events        {kept + rej}  ({kept} valid, {rej} rejected)")

    if kept + rej:
        flagged = sum(1 for e in r["events"] if e.get("needs_review"))
        unmatched = sum(1 for e in r["events"] if not e.get("venue_id"))
        print(f"  needs_review  {flagged}/{kept}   unmatched venue {unmatched}/{kept}")

    # The hallucination counters. Printed even at zero, because a zero here is the claim
    # being made and it should be visible that it was checked.
    offered = sum(1 for a in r["per_article"]
                  for x in a.get("repairs", []) if "not offered" in x)
    rewrote = sum(1 for a in r["per_article"]
                  for x in a.get("repairs", []) if "rewritten by model" in x)
    print(f"  venue_id not offered  {offered}    source field rewritten  {rewrote}")

    u = r["usage"]
    print(f"  tokens        in {u['input_tokens']:,}  out {u['output_tokens']:,}  "
          f"cache write {u['cache_creation_input_tokens']:,}  "
          f"read {u['cache_read_input_tokens']:,}")
    print(f"  wall clock    {r['seconds']}s  ({r['seconds'] / len(articles):.1f}s/article)")
    print(f"  cache hits    {r['cache_hits']}/{len(articles)}  (already paid for)")
    print(f"  cost          ${cost(u):.2f} at the {RATES_CHECKED} rates in PRICE_PER_MTOK "
          f"— verify before quoting")

    for a in failed[:10]:
        print(f"    ! {a['source_file']}@{a['source_offset']}: {a['error']}")
    for x in r["rejected"][:10]:
        print(f"    x {x['problems']}")

    OUT.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text(json.dumps(r["events"], indent=2))
    REJECTED.write_text(json.dumps(r["rejected"], indent=2))
    REPORT.write_text(json.dumps(
        {k: v for k, v in r.items() if k not in ("events", "rejected")}, indent=2))
    print(f"\n  wrote {EVENTS.relative_to(ROOT)}  "
          f"{REJECTED.relative_to(ROOT)}  {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
