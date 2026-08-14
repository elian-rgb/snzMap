# Handoff

**Written 2026-08-14 for Kiki, and for whoever picks up the code after her.**

This is the front door. It tells you what the thing is, what is actually true about it today,
how to open it, how to put more data in, and where to look for everything else. It does not
repeat what the other three documents already say — it tells you which one to open.

---

## 1. What this is

A console that maps **institutional food-service contracts** — who runs the concessions at a
given stadium, arena, convention center or ballpark, and when they ran it.

It is built from two very different kinds of evidence, and the difference matters more than
anything else in this document:

| | Where it comes from | How much you can lean on it |
| --- | --- | --- |
| **The venue spine** — 7,494 places | Wikidata + OpenStreetMap | Solid. This is a census of a defined class of buildings. |
| **Government layers** — federal awards, wage & hour, ACS | Public files, downloaded and joined under stated rules | Solid. Every join gate is written down and every excluded row is tagged with why. |
| **The contract layers** — who ran what, when | An AI model reading 602 newspaper articles | **A sample, and a small one.** 70% precision, measured, wide interval. Recall never measured. |

Everything on the map is labelled with which of those three it is. **Do not remove that
labelling.** It is the only thing keeping the contract layers honest.

---

## 2. Start here — the first five minutes

```bash
cd SNZMap/console
bun install          # first time only
bun run dev
```

Open **http://localhost:5892**. The root path goes straight in; `/console` asks for a login,
and in production every path does. It is `snz` / `netzero` — a deterrent on an internal tool,
not security. Set in `console/server.ts`, overridable with `CONSOLE_USER` /
`CONSOLE_PASSWORD`.

You will see a grey map of the United States covered in dots. Every dot is a venue in the
spine. **Grey means "we have no operator on record for this venue in this year"** — which the
sidebar says out loud, because a grey dot is a documented gap, not an empty building.

Then do these four things in order. They are the whole console:

1. **Drag the year slider** at the bottom. The map is a time machine; everything above
   responds to the year you are sitting in.
2. **Open "By company"** in the sidebar and click an operator. Now only the venues with that
   operator on record are coloured.
3. **Open "From the articles."** Seven venues are listed. Click **Drexel University** — the
   map flies there and the venue panel opens.
4. **Read the venue panel.** This is where a single venue's whole story is: its operator
   history, any federal awards naming it, the neighbourhood around it, and what the building
   used to be called. Wage-and-hour is deliberately *not* here — it is known per operator, not
   per venue, and the panel says so rather than implying a join that does not exist.

---

## 3. The four documents, and when to open which

| Document | Open it when |
| --- | --- |
| **HANDOFF.md** (this one) | You are new, or you have been away and want the current state. |
| **[ADDING_DATA.md](ADDING_DATA.md)** | You have files to add, or a spreadsheet to load, or you are filling in the gold rows. This is the operating manual. |
| **[NEXT_STEPS.md](NEXT_STEPS.md)** | You are deciding what to build next. Two builds are fully scoped, costed and deliberately **not** started. |
| **[README.md](README.md)** | You want to know *why* something was built the way it was. It is a 1,600-line build log with every decision and every defect found, in order. It is a reference, not a read-through. |

---

## 4. What is true right now

Every number below is reproducible from this repo. None is typed by hand into the interface —
the console reads them off the data files, so they stay true when the data changes.

```
SPINE           7,494 venues       stadiums, arenas, ballparks, convention centers,
                                   golf courses, ski resorts
                6,884 of them placeable in a given year; 6,469 drawn in 2015

CORPUS            602 articles parsed
                  366 had text and reached extraction
                  236 are page scans with no text layer — never read by anything

EXTRACTION        178 events, 0 rejected, 0 invented venue ids, $12.85
                   31 of those name a venue in the spine
                   18 distinct claims behind those 31 (the rest is repeat coverage)

DELIVERABLE       102 operator runs
                   11 of them mappable, across 7 venues
                      Aramark 5, Sodexo 4, Compass 1, Harry M. Stevens 1

QUALITY            20 events hand-judged, 14 correct
                      70% — but the honest statement is 48–86% at 95% confidence
                      judged by the pipeline's own author, NOT independently
                   recall: never measured

CONSOLE             8 layers carry real data; 10 are marked `planned` and say so
```

Reproduce any of it:

```bash
.venv/bin/python -m pipeline.add --publish     # rebuilds and reprints all of it, free
```

---

## 5. The two things to understand before you trust the map

### 5a. The corpus and the spine are about different worlds

**83% of what the pipeline extracted names a place this map is not a census of.**

```
178 extracted events
 31  name a venue in the spine   <- what is on the map
147  do not                      <- 83%
```

Those 147 are universities, prisons and hospitals. They are *real contracts, correctly
extracted* — they are just not stadiums. The article archive was assembled against one
definition of "institutional food service" and the venue spine against another.

This is not a bug and it is not fixable by improving extraction. It is a scope decision, and
it is written up as **build C** in [NEXT_STEPS.md](NEXT_STEPS.md), including the part that is
your call and not an engineer's: adding universities to the spine changes what the map claims
to be, and the "6,469 of 6,884" denominator in the sidebar would have to mean something else.

### 5b. The events that are *on the map* are the ones most likely to be wrong

This falls out of the audit and it is uncomfortable, so it is stated plainly:

| Sampled events | Judged correct | Precision |
| --- | --- | --- |
| On the map (matched a spine venue) | 1 of 4 | 25% |
| Off the map (no spine venue) | 13 of 16 | 81% |

Four rows is far too few to conclude much — the interval on that 25% runs from 5% to 70%. But
the direction makes sense and it has a named cause: an event only reaches the map by matching
a venue name, and **matching is exactly where the errors are**. The audit caught `"Temple"`
loosely matching `"temple terrace golf and country club"`, and a campus-wide University of
Texas at Arlington contract pinned to the football stadium.

**What to do with this:** it is the single strongest argument for the independent re-judgment
described in §7. It is also the reason build C is risky — a bigger spine means more candidate
names and more chances to match the wrong one. Re-run the audit after any spine change.

---

## 6. Adding data

Full detail is in **[ADDING_DATA.md](ADDING_DATA.md)**. The short version:

### Articles — the path that works

Put your files in a folder anywhere (`.txt` `.html` `.rtf` `.pdf` `.docx`), then:

```bash
.venv/bin/python -m pipeline.add ~/Desktop/new-articles
```

This copies the files in, hashes them, parses them, and then **stops and tells you what the
paid step would cost.** Nothing has been charged. The map has not changed. Read the number.

To go through with it:

```bash
set -a; . ./.env; set +a                                    # loads the API key
.venv/bin/python -m pipeline.add ~/Desktop/new-articles --spend
```

That extracts, pairs the events into operator runs, writes the map files and copies them into
the console. **Extraction costs about 3.5¢ per article** and is the only step in the entire
project that costs money.

To rebuild the map from data already on disk — no API key, no charge, use this after editing
anything by hand:

```bash
.venv/bin/python -m pipeline.add --publish
```

**Re-running is safe.** Files already collected are skipped by content hash; extractions
already paid for are read from a cache. Running the same folder twice republishes without
paying twice.

### Three things that will bite you

- **Scanned PDFs do not work.** A PDF that is page images with no text layer is refused rather
  than silently returning nothing. 236 of the 602 articles in the current corpus are exactly
  this. Getting them in needs OCR — that is **build D** in [NEXT_STEPS.md](NEXT_STEPS.md),
  and the cheaper first move is to try re-exporting them from ProQuest *with* full text.
- **Check `body share` after parsing.** It is printed at the end of the parse. It should be
  around 79%. The first real export came in at **2.7%** and everything downstream still looked
  fine — 4 files, 4 articles, a median body of 28 characters. The pipeline was "working" and
  producing nothing.
- **Never copy `pipeline/output/*.geojson` with a glob.** That folder also holds the federal,
  spine and ACS layers, whose copies there can be *older* than what the console is already
  serving — so the glob silently rolls an unrelated layer backwards. `--publish` copies only
  the two files it actually rewrote. Use it.

### A spreadsheet, rather than articles

There is deliberately **no generic CSV loader**. Every source joins to a venue by a different
key and needs different scope rules, so each one is its own module. The eight-step shape for
writing one is in [ADDING_DATA.md](ADDING_DATA.md) → *Path B*.

The instructive example: the labor loader *could* join wage-and-hour cases to venues by ZIP
code, and refuses to. One ZIP in that data holds 179 cases and 420 venues. A shared ZIP is a
coincidence, not evidence, and a map that drew that join would be inventing a fact.

---

## 7. What is waiting on you specifically

Neither of these needs an engineer. Both block the numbers on the map from meaning anything,
and both are cheap.

### 7a. An independent judgment of 20 rows

The current 70% precision was judged by the person who wrote the pipeline. `audit_summary.json`
records `"independent": false` and the console prints *"Judged by the pipeline's author, not
independently"* underneath the figure. A second person re-judging the same 20 rows turns a
self-report into a measurement.

The tooling is built and each row already carries the article excerpt the claim came from, so
judging one is reading a paragraph, not hunting through a 600-article file:

```bash
.venv/bin/python -m pipeline.audit.sample --n 20     # writes output/audit_sample.csv
# fill in the `verdict` column
.venv/bin/python -m pipeline.audit.score --auditor "Kiki"
cp pipeline/output/audit_summary.json console/public/data/
```

Given §5b, it is worth over-sampling the events that are **on the map**. Four is not enough to
know whether that 25% is real.

### 7b. The 24 gold rows

**Recall has never been measured.** We know how often the pipeline is right about what it
found. We have no idea what it missed.

`pipeline/output/gold_seed.csv` is already seeded with 24 venues — current MLB, NFL, NBA and
NHL home venues. Identity is filled in: exact spelling, city, state, coordinates. Seven columns
are yours to fill, because they are the actual knowledge being captured: operator, start and
end dates, how sure you are of each, and **where you got it**. (`exit_mode`, `notes` and
`extras` are also empty and are optional — leave them alone unless you have something to say.)

The full instructions are in [ADDING_DATA.md](ADDING_DATA.md) → *Filling in the gold rows*.
Four rules from there are worth repeating because breaking any one makes the result worthless:

1. **Do not fill them in from this project's own output.** The gold set is the ruler. Reading
   it off the thing being measured makes the ruler agree with itself.
2. **`ongoing` and `unknown` are opposites.** One asserts they still hold it; the other admits
   you never found the end. The map paints them differently.
3. **Write `verify` in the `source` column if you are going from memory.** Those rows are
   excluded from scoring rather than trusted.
4. **Fill in all 24, including the ones you expect the pipeline to miss.** That mix is the only
   thing that separates *"the extractor failed"* from *"no article in the archive mentions this
   place."*

This is the one place in the whole project where hand-typed data is expected, and it is
deliberately not the pipeline author's job to write it.

---

## 8. Navigating the console

The sidebar is seven collapsible sections, top to bottom. Each one answers a different
question about whatever the year slider is set to.

| Section | What it answers | Backed by |
| --- | --- | --- |
| **Venue spine** | What buildings exist, and how many have an operator on record | Wikidata + OSM |
| **By company** | Where does Aramark / Sodexo / Compass appear at all | Federal + labor records |
| **By neighbourhood** | Who lives around these venues — transit, commute, income | ACS |
| **From the articles** | Which venues the newspaper corpus actually speaks to | The AI pipeline |
| **Federal awards** | Government contracts naming a venue in the spine (8 of 9,672 matched) | USAspending |
| **Wage & hour** | Back wages and violations, **by operator, never by venue** | DOL WHD |
| **Neighbourhood context** | The ACS choropleth behind the dots | ACS |

Click any dot for the **venue panel**: operator history, federal awards naming that venue,
neighbourhood context, and name history — including former names, which is how you tell that
a 1997 article about "Veterans Stadium" is about the building you are looking at.

Four things that are easy to misread:

- **Grey is not "no data exists."** Grey is *"no operator on record for this venue in this
  year."* The sidebar states the count so it can never be mistaken for an empty map.
- **A painted run stops where the evidence stops.** If an article reports an award in 1998 and
  nothing ever reports an ending, the map paints up to the last date any article places that
  operator there — not to today. Every run in the venue panel prints which of the three it is:
  *end reported*, *still held as of last coverage*, or *evidence stops here; the end is
  unknown.* Those are three different facts and the panel never blurs them.
- **"From the articles" shows `8 ×19`.** Eight distinct claims, nineteen articles reporting
  them. Repeat coverage of one contract is drawn once and counted as corroboration — three
  papers covering one award is one contract with three sources, not three contracts.
- **Colour is never the only signal.** Every colour in the console is within ~1.2 luminance of
  some other colour in it, so hue alone cannot carry a distinction. Rings differ in radius as
  well as colour, which is the part that survives a grayscale print. If you change a colour,
  check it in grayscale.

---

## 9. Navigating the repo

```
SNZMap/
├── HANDOFF.md ADDING_DATA.md NEXT_STEPS.md README.md
│
├── console/                     the map
│   ├── server.ts                Hono server, port 5892, basic auth
│   ├── public/data/             ← WHAT THE CONSOLE ACTUALLY READS
│   └── src/
│       ├── layerRegistry.ts     every layer, ready or planned, and its description
│       ├── components/          Sidebar, MapView, VenuePanel, FederalPanel
│       └── utils/               one transform per layer
│
└── pipeline/                    everything that makes data
    ├── add.py                   ← THE ONE COMMAND. Start here.
    ├── schema.py                field definitions + validation for every record type
    ├── spine/                   Wikidata + OSM -> the 7,494 venues
    ├── ingest/                  files -> articles.json  (collect, parse, formats)
    ├── extract/                 articles -> events, via the model  (the only paid stage)
    ├── spans/                   events -> operator runs; also the gold set and its gates
    ├── emit/records.py          runs + events -> the geojson and csv the console reads
    ├── audit/                   precision sampling and scoring
    ├── federal/ labor/ acs/     the government layers
    └── output/                  everything the pipeline writes
```

**The one structural thing to know:** `pipeline/output/` is *not* what the console reads.
`console/public/data/` is. Copying between them is a real step and it is the step people
forget — which is why `pipeline.add --publish` exists and does it correctly.

### Where a claim comes from, in one line each

```
pipeline/articles/raw/…        the actual newspaper file, openable by a person
  -> output/articles.json      one record per article, with problems listed
  -> output/contract_events.json   one row per extracted claim, with source_file
  -> output/tenure_records.json    one row per operator run, with derived_from
  -> console/public/data/*.geojson what the map draws
```

Every row at every stage carries enough provenance to walk that chain backwards to a sentence
in a file. `contract_events.csv` is deliberately kept **uncollapsed** for exactly this reason —
it holds every extracted event, even the repeat coverage the map draws only once.

---

## 10. Checking nothing is broken

All free, all offline, all fast. Run them after any change:

```bash
.venv/bin/python -m pipeline.check_end_to_end     # 36 checks: a USB stick -> dots on a map
.venv/bin/python -m pipeline.spans.check_rules    # 18 checks: the span-pairing rules
cd console && bun run typecheck
```

Each prints `PASS` or names exactly what failed. The end-to-end runs the real code against a
fake USB stick of fixture articles, so it never touches the real data or the API.

There is also a review queue for things the pipeline refused to decide by itself:

```
output/review_queue.csv    912 rows, but only 14 need a person
```

The other 898 are sorted into three categories that are explicitly **not** a reviewer's job:
499 defective source documents, 388 correctly-extracted-but-out-of-scope venues, and 11
documented silences. Open the file and work down from the top — it is sorted so your own work
is first.

---

## 11. What is deliberately not built

Scoped, costed, and left alone on purpose. Full write-ups with reproduce commands in
**[NEXT_STEPS.md](NEXT_STEPS.md)**.

| | What it buys | What it costs | The catch |
| --- | --- | --- | --- |
| **C — universities into the spine** | ~64 more mappable events; the contract layer roughly triples | $12.85 + ~2h re-extraction, plus re-running the audit | Changes what the map *claims to be*. Kiki's call, not an engineer's. |
| **D — OCR the page scans** | ~115 more events from the 236 unread articles | An OCR pass + ~$8.30 | OCR errors do not fail loudly. Try re-exporting from ProQuest first — an afternoon on export settings may beat a week on OCR. |

Also recorded there: a cosmetic defect where every `source_publication` reads
`|University Wire; Carlsbad |` with stray table bars from the RTF conversion. It is a four-line
parser fix, but the publication name is part of what the model was shown, so correcting it
invalidates 361 of 366 cached extractions — **$12.67 to fix a cosmetic string.** It should ride
along with build C, which already pays that cost for a much better reason.

**Neither C nor D should start before §7 is done.** Both are expensive, and without an
independent precision figure and a measured recall, either one could raise the numbers on the
map with no way of telling whether it raised the *true* ones.

---

## 12. The standard this was held to

Stated here because it is the thing most likely to be lost in a handoff, and because every
awkward decision in this repo follows from it:

> **A wrong big number is far worse than a missing right small one.**

That is why the map covers 7 venues instead of 700, why the sidebar says *"48–86% at 95%
confidence"* instead of *"70%"*, why 10 layers are marked `planned` rather than quietly
dropped, why a documented silence gets its own category, and why the 83% scope mismatch is
written at the top of a document instead of at the bottom of a backlog.

If you change one thing about how this project works, do not change that.
