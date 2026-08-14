# Next steps

Two builds were scoped on 2026-08-14 and deliberately **not started**, because neither could
be finished and verified before the handoff. Both are written up here with the measurements
that justify them, so the next person inherits the reasoning and not just the conclusion.

Everything below is a number this repo can reproduce. Commands to re-derive them are given.

---

## The finding that motivates both

**83% of what the pipeline extracted names a place this map is not a census of.**

```
178 extracted events
 31  name a venue in the spine   <- what is on the map
147  do not                      <- 83%
```

Broken down by what kind of institution the 147 name:

| Kind | Events | Examples |
| --- | --- | --- |
| University / college | 57 across 15 names (+7 more as bare "Temple") | Temple University (19), U of L, SMSU, University of Maine System |
| Corrections | 24 | Michigan DOC (6), Tennessee DOC (5) |
| Healthcare | 12 | Mayo Clinic (6) |
| Other | 54 | |

The spine is 7,494 venues — stadiums, arenas, ballparks, convention centers, golf courses,
ski resorts. The article corpus is overwhelmingly about **universities, prisons and
hospitals.** The two were assembled against different definitions of "institutional food
service", and that mismatch, not extraction quality, is what bounds the map.

The console states this rather than hiding it, and the contract layers are labelled a sample
rather than a census. **That labelling is doing real work — do not remove it without doing
one of the two builds below.**

```bash
# reproduce
.venv/bin/python -c "
import json,collections
ev=json.loads(open('pipeline/output/contract_events.json').read())
un=[e for e in ev if not e.get('venue_id')]
print(len(un),'of',len(ev),'unmapped')
print(collections.Counter((e.get('venue_name_as_written') or '?').strip() for e in un).most_common(15))"
```

---

## C — Universities into the spine

**What it buys.** Roughly **64 of the 147 unmapped events** become mappable — mapped events
go from 31 to about 95, tripling the contract layer. It is the single largest coverage gain
available, and it targets the exact institutions the corpus is actually about.

**What it costs.**

| | |
| --- | --- |
| Wikidata pull + spine rebuild | A few hours. `pipeline/spine/wikidata.py` already implements this exact pattern for venues — US colleges and universities are a well-populated Wikidata class with coordinates. |
| **Re-running extraction** | **$12.85 and ~2 hours.** Unavoidable — see below. |
| Re-running the precision audit | ~1 hour of a person's time. Also unavoidable — see below. |

**Why extraction must be re-run.** Candidate venues are offered to the model *at extraction
time*; `venue_id` is chosen from that offered list and validated against it, precisely so the
model cannot invent an identity. A larger spine changes the candidate list, which changes
every payload, which misses the response cache. There is no cheap post-hoc join that
preserves the existing safety property. **Do not be tempted to bolt on a name-matching pass
over `venue_name_as_written`** — that reintroduces exactly the trust the prompt is built to
withhold.

**The risk, which is measured and not hypothetical.** A bigger spine means more candidates
per article and more chances to match the wrong one. The precision audit already caught this
failure mode in its mildest form: `"Temple"` loosely matched `"temple terrace golf and
country club"`. Adding thousands of universities makes near-miss names far more common.
Precision is currently 70% (14/20, 48–86% CI). **Re-run `pipeline/audit` after this change
and compare.** If precision drops, the coverage gain is not a gain — a wrong big number is
worse than a missing right small one.

**The decision that comes first, and it is not an engineering one.** This changes what the
map claims to be. Today it is a map of stadiums and arenas that happens to hold some
university contracts. After this it is a map of institutional food service generally, and
the 7,494-venue spine becomes a partial census of a much larger universe — which means the
denominator in the sidebar ("6,469 of 6,884") has to be rewritten to mean something else.
**That is Kiki's call, not the next engineer's.**

---

## D — OCR the page scans

**What it buys.** **236 of 602 articles (39%) have no text at all** — the export declared a
full-text section and supplied a page image instead. Nothing has ever read them. At the
observed rate of 0.49 events per usable article, they plausibly hold **~115 more events**.

```
602  articles parsed
366  reached extraction
236  are page scans with no text layer   <- 39% of the corpus, never read
239  separately have no headline (overlapping set)
```

**What it costs.** An OCR pass (Tesseract locally, or a vision model), plus **~$8.30** to
extract the recovered text at the measured 3.5¢/article, plus the work of wiring OCR into
`pipeline/ingest/parse.py` behind the existing lazy-import pattern.

**The risk.** OCR errors do not fail loudly — they produce plausible-looking wrong strings.
A misread operator or venue name yields a confidently wrong row, which is worse than the
current honest gap. Mitigation, in order: put OCR'd articles behind a distinct
`source_label` so they can be excluded; audit them **separately** from the clean corpus so
one precision figure does not launder the other; treat a drop in `extraction_confidence` on
OCR'd articles as the signal to stop.

**Cheaper first move.** Before building any of this, check whether the articles can simply be
re-exported *with* their full text. 236 missing full-text sections looks like an export
setting, not a scanning problem. **An afternoon on the ProQuest/Nexis export options may be
worth more than a week on OCR.** Do this first.

```bash
# reproduce
.venv/bin/python -c "
import json
a=json.loads(open('pipeline/output/articles.json').read())
print(len(a),'articles;',sum(1 for x in a if not x.get('body_text')),'with no body text')"
```

---

## What to do before either

Both builds are expensive and neither is measurable without these, which cost no engineering
time at all:

1. **An independent precision judgment.** The current 70% was judged by the pipeline's own
   author; `audit_summary.json` records `"independent": false` and the console says so. A
   second person re-judging the same 20 rows turns it into a measurement. Tooling is built:
   `pipeline.audit.sample` then `pipeline.audit.score --auditor "name"`.
2. **The 24 seeded gold rows.** Recall has never been measured. The rows are seeded and
   waiting in `pipeline/output/gold_seed.csv`; see *Filling in the gold rows* in
   [ADDING_DATA.md](ADDING_DATA.md).

Without these, C and D can raise the numbers on the map with no way to tell whether they
raised the *true* ones.
