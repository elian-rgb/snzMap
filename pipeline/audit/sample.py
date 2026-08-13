"""Draw an auditable sample of extracted events and print the evidence beside each claim.

Why this exists
---------------
`pipeline.spans.evaluate` measures **recall** — of the runs that exist in the world, how
many did the pipeline find? It needs gold rows written from outside the system, which is
why it is Kiki's job and why it is still ungated.

Nothing measures **precision** — of the events the pipeline *did* produce, how many are
true? That question can be answered today, without any new research, because every event
carries the article it came from and every article is already on disk. A reader can judge
the claim against the text that produced it.

Why a random sample and not `review_queue.csv`
----------------------------------------------
The review queue holds the records the pipeline already doubted. Auditing only those would
measure the pipeline's self-doubt, not its accuracy, and would report a precision far below
the truth. The sample here is drawn uniformly at random from **all** events, flagged or
not, so the resulting fraction is an unbiased estimate of corpus precision.

It is not stratified by operator. The corpus is roughly 83% Aramark, so the sample will be
too — that is the corpus being what it is, and reweighting it would produce a number about
a corpus nobody has. The composition is printed so the imbalance is visible rather than
hidden.

The sample is seeded, so re-running produces the same rows and a half-finished audit is
never invalidated by a re-run.

    .venv/bin/python -m pipeline.audit.sample --n 20
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "output"
EVENTS_IN = OUT / "contract_events.json"
ARTICLES_IN = OUT / "articles.json"
SAMPLE_OUT = OUT / "audit_sample.csv"

# Long enough to carry operator, venue, action and date in one window. The review queue's
# 260 chars is right for triage and too short to settle a claim.
EXCERPT_CHARS = 700

DEFAULT_SEED = 20260813

# Filled in by a human. Anything outside this set is reported as unrecognised rather than
# quietly ignored — a typo'd verdict must not silently become a pass.
VERDICTS = {
    "correct": "article supports the operator, the venue and the event type",
    "wrong_operator": "article names a different company",
    "wrong_venue": "article is about a different place",
    "wrong_event_type": "won/lost/renewed/self-op is backwards or wrong",
    "wrong_date": "operator, venue and type are right; the date is not",
    "out_of_scope": "correctly extracted, but it is not a food service contract",
    "not_supported": "the article does not say this at all",
    "cant_tell": "the excerpt is not enough to judge — not counted either way",
}

COLUMNS = [
    "verdict", "auditor_note",
    "claim", "excerpt",
    "source_publication", "source_date", "source_title", "source_file",
    "event_type", "event_date", "date_precision",
    "operator", "venue_name_as_written", "on_the_map",
    "extraction_confidence", "pipeline_flagged_it", "event_id",
]

# Curly punctuation from ProQuest exports breaks naive substring matching: an event may
# carry "Leo O'Donovan" while the body says "Leo O\u2019Donovan".
_FOLD = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}


def _fold(s: str) -> str:
    for a, b in _FOLD.items():
        s = s.replace(a, b)
    return s.lower()


def _articles_for(ev: dict[str, Any], articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    key = (ev.get("source_file"), ev.get("source_title"), ev.get("source_date"))
    exact = [a for a in articles
             if (a.get("source_file"), a.get("source_title"), a.get("source_date")) == key]
    return exact or [a for a in articles if a.get("source_file") == ev.get("source_file")]


def excerpt_for(ev: dict[str, Any], articles: list[dict[str, Any]]) -> tuple[str, int]:
    """The window of article text a person needs to judge this event.

    Returns the excerpt and how many candidate articles shared the citation. ProQuest
    exports the same piece more than once, so >1 is usually a reprint rather than a real
    ambiguity — but the count is surfaced instead of assumed.
    """
    candidates = _articles_for(ev, articles)
    if not candidates:
        return "", 0

    needles = [n for n in (ev.get("venue_name_as_written"), ev.get("institution"),
                           ev.get("operator")) if n]

    best: tuple[int, str] = (-1, "")
    for a in candidates:
        body = " ".join((a.get("body_text") or "").split())
        if not body:
            continue
        folded = _fold(body)
        at = next((i for i in (folded.find(_fold(n)) for n in needles) if i >= 0), -1)
        # Prefer the article that actually contains the thing being claimed; among those,
        # the longest body, since the shorter duplicate is usually a truncated reprint.
        score = (1_000_000 if at >= 0 else 0) + len(body)
        if score <= best[0]:
            continue
        if at < 0:
            window = body[:EXCERPT_CHARS] + ("\u2026" if len(body) > EXCERPT_CHARS else "")
        else:
            start = max(0, at - EXCERPT_CHARS // 3)
            end = min(len(body), start + EXCERPT_CHARS)
            window = (("\u2026" if start else "") + body[start:end]
                      + ("\u2026" if end < len(body) else ""))
        best = (score, window)

    return best[1], len(candidates)


def claim_sentence(ev: dict[str, Any]) -> str:
    """The event restated as a sentence, so the auditor judges a claim and not a row."""
    verb = {
        "won": "won the food service contract at",
        "lost": "lost the food service contract at",
        "renewed": "renewed its food service contract at",
        "self_op": "was replaced by in-house operation at",
    }.get(ev.get("event_type") or "", f"had a '{ev.get('event_type')}' event at")

    when = ev.get("event_date") or "date unknown"
    if ev.get("date_precision") and ev.get("event_date"):
        when = f"{when} ({ev['date_precision']})"
    where = ev.get("venue_name_as_written") or "(no venue named)"
    if ev.get("institution") and ev["institution"] != where:
        where = f"{where}, {ev['institution']}"
    return f"{ev.get('operator') or '(no operator)'} {verb} {where} — {when}."


def build_sample(events: list[dict[str, Any]], articles: list[dict[str, Any]],
                 n: int, seed: int) -> list[dict[str, Any]]:
    picked = random.Random(seed).sample(events, min(n, len(events)))
    rows = []
    for ev in picked:
        excerpt, ncand = excerpt_for(ev, articles)
        if ncand > 1:
            excerpt = f"[{ncand} copies of this article in the corpus; showing the fullest] {excerpt}"
        rows.append({
            "verdict": "",
            "auditor_note": "",
            "claim": claim_sentence(ev),
            "excerpt": excerpt,
            "source_publication": (ev.get("source_publication") or "").strip("| "),
            "source_date": ev.get("source_date"),
            "source_title": ev.get("source_title"),
            "source_file": ev.get("source_file"),
            "event_type": ev.get("event_type"),
            "event_date": ev.get("event_date"),
            "date_precision": ev.get("date_precision"),
            "operator": ev.get("operator"),
            "venue_name_as_written": ev.get("venue_name_as_written"),
            "on_the_map": "yes" if ev.get("venue_id") else "no",
            "extraction_confidence": ev.get("extraction_confidence"),
            "pipeline_flagged_it": "yes" if ev.get("needs_review") else "no",
            "event_id": ev.get("event_id"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=20, help="sample size (default 20)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing sample even if verdicts are filled in")
    args = ap.parse_args()

    events = json.loads(EVENTS_IN.read_text())
    articles = json.loads(ARTICLES_IN.read_text())

    if SAMPLE_OUT.exists() and not args.force:
        with SAMPLE_OUT.open() as fh:
            filled = sum(1 for r in csv.DictReader(fh) if (r.get("verdict") or "").strip())
        if filled:
            print(f"{SAMPLE_OUT.name} already has {filled} verdict(s) filled in — not "
                  f"overwriting.\n  Re-run with --force only if you mean to discard them.")
            return 1

    rows = build_sample(events, articles, args.n, args.seed)
    with SAMPLE_OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    no_excerpt = sum(1 for r in rows if not r["excerpt"])
    print(f"wrote {SAMPLE_OUT.relative_to(OUT.parent.parent)}  "
          f"({len(rows)} of {len(events)} events, seed {args.seed})")
    print(f"  already flagged by the pipeline : {sum(1 for r in rows if r['pipeline_flagged_it'] == 'yes')}")
    print(f"  on the map                      : {sum(1 for r in rows if r['on_the_map'] == 'yes')}")
    if no_excerpt:
        print(f"  !! no article text found        : {no_excerpt} (judge these from the source file)")

    ops: dict[str, int] = {}
    for r in rows:
        head = (r["operator"] or "?").split()[0]
        ops[head] = ops.get(head, 0) + 1
    print("  operators                       : "
          + ", ".join(f"{k} {v}" for k, v in sorted(ops.items(), key=lambda x: -x[1])))

    print("\nFill in the `verdict` column. Allowed values:")
    for k, v in VERDICTS.items():
        print(f"  {k:18} {v}")
    print("\nThen: .venv/bin/python -m pipeline.audit.score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
