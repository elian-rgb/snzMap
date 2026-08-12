"""Find which spine venues an article actually mentions.

The extraction prompt needs the spine, but the spine is 7,511 venues with ~20k match keys
and will not fit in a prompt — and even if it did, a model asked to pick from 7,511 options
picks badly. So the venue list is narrowed *before* the model sees it, by string matching
against the article text, and the model's job shrinks to choosing among a handful of real
candidates or saying none fit.

This also means `venue_id` can never be hallucinated: it is only ever copied from a
candidate the pipeline supplied, and the extractor validates that it was.

Matching is token-based rather than substring-based. "Gardens" must not match "Garden",
and a 20k-key substring scan per article is too slow to run over a 20-year corpus. Each key
is triggered by its rarest token, then verified as a contiguous phrase.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..spine.build_spine import is_type_phrase, match_key
from ..spans.gold import open_at, year_of

SPINE = Path(__file__).resolve().parent.parent / "output" / "venues_full.json"

MAX_CANDIDATES = 25

# Every sentence capitalizes its first word, so an occurrence there carries no information
# about whether "Pond" is the arena or the water.
_SENTENCE_BREAK = re.compile(r'(?:^|[.!?:;]["\'\)\]]?\s+|\n\s*|["\u201c]\s*)$')


def appears_capitalized(word: str, text: str) -> bool:
    """Is `word` printed as a proper noun somewhere in `text`?

    The spine flags keys that are also ordinary English words — `pond`, `jake`, `cell`,
    `barn`. All four are real venue nicknames and all four appear in ordinary prose, and the
    only thing that separates the two uses is the capital letter a newspaper gives a name.
    """
    for m in re.finditer(rf"\b{re.escape(word)}\b", text, re.I):
        if not m.group(0)[0].isupper():
            continue
        if _SENTENCE_BREAK.search(text[max(0, m.start() - 40):m.start()]):
            continue
        return True
    return False


def build_index(venues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """key -> venues, plus a trigger-token index so scanning is cheap."""
    if venues is None:
        venues = json.loads(SPINE.read_text())

    cased_keys: set[str] = set()
    key_to_venues: dict[str, list[dict[str, Any]]] = {}
    for v in venues:
        for key, window in v.get("match_keys", {}).items():
            # The spine keeps a pure category name when it is a venue's only one (an OSM way
            # literally labelled "Convention Center"). Searching on it is still wrong: it
            # would attach that one anonymous building to every article mentioning a
            # convention center. The record stays; it is just not reachable by text scan.
            if is_type_phrase(key) or len(key) < 4:
                continue
            key_to_venues.setdefault(key, []).append(v)
            if window.get("cased"):
                cased_keys.add(key)

    # Trigger = the key's rarest token, so "madison square garden" is looked up by
    # "madison", not by "garden" which appears in hundreds of keys.
    df = Counter(tok for key in key_to_venues for tok in set(key.split()))
    trigger_to_keys: dict[str, list[str]] = {}
    for key in key_to_venues:
        trigger = min(key.split(), key=lambda t: (df[t], -len(t)))
        trigger_to_keys.setdefault(trigger, []).append(key)

    return {
        "key_to_venues": key_to_venues,
        "trigger_to_keys": trigger_to_keys,
        "cased_keys": cased_keys,
    }


def find_candidates(
    text: str,
    index: dict[str, Any],
    article_year: int | None = None,
    limit: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Spine venues plausibly named in `text`, most specific first."""
    tokens = match_key(text).split()
    positions: dict[str, list[int]] = {}
    for i, tok in enumerate(tokens):
        positions.setdefault(tok, []).append(i)

    cased_keys = index.get("cased_keys") or set()
    hits: dict[str, dict[str, Any]] = {}
    for trigger, keys in index["trigger_to_keys"].items():
        if trigger not in positions:
            continue
        for key in keys:
            if key in cased_keys and not appears_capitalized(key, text):
                continue
            key_tokens = key.split()
            offset = key_tokens.index(trigger)
            for p in positions[trigger]:
                start = p - offset
                if start >= 0 and tokens[start:start + len(key_tokens)] == key_tokens:
                    for v in index["key_to_venues"][key]:
                        prev = hits.get(v["venue_id"])
                        # Keep the longest key that hit: "busch memorial stadium" is better
                        # evidence than "busch stadium".
                        if prev is None or len(key) > len(prev["matched_key"]):
                            hits[v["venue_id"]] = {"venue": v, "matched_key": key}
                    break

    candidates = []
    for hit in hits.values():
        v, key = hit["venue"], hit["matched_key"]
        alias_window = v.get("match_keys", {}).get(key) or {}
        cand = {
            "venue_id": v["venue_id"],
            "canonical_name": v["canonical_name"],
            "matched_as": key,
            "venue_type": v.get("venue_type"),
            "city": v.get("city"),
            "state": v.get("state"),
            "opened_date": v.get("opened_date"),
            "closed_date": v.get("closed_date"),
            "capacity": v.get("capacity"),
            "name_is_ambiguous": v.get("name_is_ambiguous", False),
        }
        if alias_window.get("start_date") or alias_window.get("end_date"):
            cand["name_used"] = f"{alias_window.get('start_date') or '?'} to {alias_window.get('end_date') or 'present'}"
        if article_year is not None:
            # Not a filter. A 2005 article can discuss a venue demolished in 1968, and
            # dropping the candidate would force the model to invent one. Flagging it lets
            # the model weigh it — and lets the extractor spot a bad pick afterwards.
            cand["plausible_at_article_date"] = open_at(v, key, article_year)
        candidates.append(cand)

    # Capacity breaks ties because `limit` really does bite: 30 venues own the key
    # "memorial stadium", and cutting that list alphabetically dropped Minneapolis's
    # 56,000-seat one while keeping a 6,516-seat one. A shared name's contract-relevant
    # venues are the big ones. It is only a tiebreak — an exactly-matched short name still
    # outranks a big venue that matched loosely.
    candidates.sort(
        key=lambda c: (
            not c.get("plausible_at_article_date", True),
            -len(c["matched_as"]),
            -(c["capacity"] or 0),
            c["canonical_name"],
        )
    )
    return candidates[:limit]


def find_for_article(article: dict[str, Any], index: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidates for a parsed article record (title + body are both searched)."""
    text = f"{article.get('source_title') or ''}\n{article.get('body_text') or ''}"
    return find_candidates(text, index, year_of(article.get("source_date")))
