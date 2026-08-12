"""Parse everything under `articles/raw/` into `output/articles.json`, then grade the run.

The gate is printed every time and is deliberately unflattering. Ingest is the stage where
failure is invisible: a splitter that merges two articles, or a header reader that swallows
the first paragraph, still produces a clean-looking file with a plausible row count. So the
numbers reported are the ones that catch that — text retained, body share, and how many
articles are missing a field the event schema requires.

    .venv/bin/python -m pipeline.ingest.run
    .venv/bin/python -m pipeline.ingest.run --limit 5 --show 2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .collect import ARTICLE_SUFFIXES, ROOT
from .parse import coverage, parse_file

RAW = ROOT / "articles" / "raw"
OUT = ROOT / "output"

# An article missing any of these can produce no valid event — schema.EVENT_FIELDS marks all
# four required. They are the reason to care about a parse failure.
REQUIRED = ("source_publication", "source_date", "source_title")


def run(raw: Path = RAW, limit: int | None = None) -> dict[str, Any]:
    files = sorted(p for p in raw.rglob("*")
                   if p.is_file() and p.suffix.lower() in ARTICLE_SUFFIXES)
    if limit:
        files = files[:limit]

    results = [parse_file(p, str(p.relative_to(ROOT))) for p in files]
    articles = [a for r in results for a in r["articles"]]
    unreadable = [{"source_file": r["source_file"], "error": r["error"]}
                  for r in results if r["error"]]

    missing: dict[str, int] = {f: 0 for f in REQUIRED}
    usable = 0
    for a in articles:
        gaps = [f for f in REQUIRED if not a.get(f)]
        for f in gaps:
            missing[f] += 1
        if not gaps and a["body_text"]:
            usable += 1

    return {
        "files_seen": len(files),
        "files_unreadable": unreadable,
        "articles": articles,
        "usable": usable,
        "missing": missing,
        "coverage": coverage(results),
        "per_file": [{"source_file": r["source_file"], "articles": len(r["articles"]),
                      "chars": r["chars"], "dropped_chars": r["dropped_chars"]}
                     for r in results],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--limit", type=int, help="parse only the first N files")
    ap.add_argument("--show", type=int, default=0, help="print the first N parsed articles")
    args = ap.parse_args()

    if not args.raw.exists():
        raise SystemExit(f"nothing to parse: {args.raw} does not exist "
                         f"(run pipeline.ingest.collect first)")

    r = run(args.raw, args.limit)
    articles = r["articles"]

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "articles.json"
    path.write_text(json.dumps(articles, indent=2))

    cov = r["coverage"]
    print(f"\nPARSE {args.raw}")
    print(f"  files      {r['files_seen']}  ({len(r['files_unreadable'])} unreadable)")
    print(f"  articles   {len(articles)}")
    print(f"  usable     {r['usable']}  (all provenance fields present + non-empty body)")
    for field, n in r["missing"].items():
        if n:
            print(f"    missing {field:<20} {n}")
    print(f"  text retained {cov['text_retained']:.1%}  body share {cov['body_share']:.1%}")

    if articles:
        lengths = sorted(len(a["body_text"]) for a in articles)
        mid = lengths[len(lengths) // 2]
        print(f"  body chars    min {lengths[0]}  median {mid}  max {lengths[-1]}")
        short = [a for a in articles if len(a["body_text"]) < 400]
        if short:
            print(f"  {len(short)} article(s) under 400 chars — check the splitter")

    for u in r["files_unreadable"][:10]:
        print(f"    ! {u['source_file']}: {u['error']}")

    for a in articles[:args.show]:
        print(f"\n  --- {a['source_file']} @{a['source_offset']}")
        print(f"      {a['source_publication']!r}  {a['source_date']}  {a['source_title']!r}")
        print(f"      {a['body_text'][:200]!r}")
        if a["problems"]:
            print(f"      problems: {a['problems']}")

    print(f"\n  wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
