# SNZ Console

Historical map of institutional food service contracts. Two halves, per `SNZ_PLAN_v2.md`:

- `pipeline/` — Python. Builds the venue spine, then extracts contract history from articles.
- `console/` — Bun + Hono + Vite + React + MapLibre GL. Renders the layers by place and time.

## Status

**The contract chain runs end to end on the full corpus, and journalism is now on the map.**
The 366-article run was made on 2026-08-13: 178 events, 0 rejected, $12.85. Six layers carry
real data in the console — venue spine, federal awards, ACS context, DOL wage & hour, and now
contract events and contract tenure.

The number that bounds the last two: **31 of 178 events name a venue in this spine, across 7
venues of 6,884.** The other 147 name prisons, school districts and hospitals — real contracts
about buildings this map was never a census of. The contract layers are a sample of what the
corpus supports, labelled as one in the sidebar, not a census.

**Precision is now measured; recall still is not.** A random sample of 20 events was judged
against the article each came from: **14 correct — 48–86% at 95% confidence** (`pipeline/
audit/`). That figure and its interval are read off `audit_summary.json` by the console, so
it cannot go stale. Recall needs gold rows written from outside the pipeline and is still
1 row of 10–20 — **Kiki's to write**. The two are different questions and the console does
not report them as one number.

New here? [ADDING_DATA.md](ADDING_DATA.md) is the runbook for getting articles or a CSV onto
the map.

| Step | State |
|---|---|
| Phase 0 — venue spine | ✅ 7,494 venues, 6,884 mappable |
| Console scaffold + spine layer | ✅ renders, no API key needed |
| Schemas locked (build order 2) | ✅ `pipeline/schema.py` + eval gate |
| Gold set seeded (build order 2) | ⬜ 1 of 10–20 rows — **Kiki's to write** (recall) |
| Precision audit (`pipeline/audit`) | ✅ 20 sampled, 14 correct, 48–86% CI — author-judged, re-checkable |
| Extraction prompt + candidate finder | ✅ **real data** — venue join confirmed; 1 prompt defect found by reading rows against articles |
| Extraction runner (Phase 1.5) | ✅ 17/17 gate + live endpoint verified; 2 silent defects found and fixed |
| Ingest: collect / formats / parse / run | ✅ **real data** — 600 documents off the USB; 3 silent defects found and fixed |
| Span pairing (Phase 1.6) | ✅ 18/18 rule gate, schema-clean |
| Emit (Phase 1.7) | ✅ 6 files; has now processed rows, via the rehearsal |
| End-to-end dress rehearsal | ✅ 36/36 — a fake USB reaches the map, model answer is a fixture |
| Tenure layer in the console | ✅ wired + verified in the browser on rehearsal output |
| Federal awards (USAspending) | ✅ **real data** — 27/27 gate, 393 in-scope awards, in the console |
| ACS neighbourhood context | ✅ **real data** — 29/29 gate, 6,831 venues, in the console |
| Wage & hour enforcement (DOL WHD) | ✅ **real data** — 66/66 gate, 231 in-scope cases, in the console |
| Console verification pass | ✅ 2026-08-11 — walked end to end in a browser; 4 defects found and fixed |
| Wage & hour *by venue* | ⬜ blocked on the data, not on time — 179 cases → 420 venues |
| Real articles through the pipeline | ✅ **real data** — 366/366 extracted, 178 events, 0 rejected, 0 invented venue ids, $12.85 |
| Contract events + tenure in the console | ✅ **real data** — 31 events / 7 venues ringed and listed; span id collision found and fixed |
| Extractor accuracy | ⬜ unstated — needs 10–20 gold rows to score against |

The eight ✅ **real data** rows are the only rows in this table backed by something other than
a fixture. The contract side is no longer self-tested or a sample: the whole corpus has been
through the real model and its output is what the console draws.

What is still missing is not coverage but *validation*. The extractor has never been scored,
because scoring needs rows a human confirmed from a source they can cite, and there is one of
those. Until that exists the contract layers ship as extracted-but-ungraded, which is what the
sidebar says.

The ⬜ on wage & hour by venue is deliberate and is not going to become a ✅. WHISARD has no
venue field and ZIP is not a substitute for one; the row stays in the table so the absence is
visible rather than looking like something nobody got to.

Everything above was gate-tested before it was browser-tested, and the browser still found
four things the gates could not see: three sentences that stated a figure the data no longer
supported, including one that was already wrong, and a browser without WebGL2 taking the whole
page down instead of just the map. See
[Console verification pass](#console-verification-pass-2026-08-11).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install requests openpyxl   # pipeline
cd console && bun install                                          # console
bun run dev                                               # http://localhost:5892 (snz / netzero)
```

`bun run prod` builds and serves `dist/` instead (30 MB, of which 29 MB is the two ZCTA
boundary files). The `snz / netzero` prompt is what `server.ts` calls it in the code — "a
light deterrent on an internal research console, not real security". It gates `/console`
only: `/data/*` and `/assets/*` answer without it, verified by curl. That is fine for what
this is — every byte under `/data` is public-domain federal data, Wikidata or OSM — but it is
worth knowing before treating the prompt as access control.

The federal and ACS loaders read bulk exports out of `~/Downloads` rather than an API — the
USAspending award download and the five ACS ZCTA table folders, kept under the folder names
`data.census.gov` gives them. Both raise on a missing or renamed folder rather than emitting
an empty series.

## Rebuilding the spine

```bash
.venv/bin/python -m pipeline.spine.wikidata      # ~25 min cold, instant cached
.venv/bin/python -m pipeline.spine.overpass      # ~5 min
.venv/bin/python -m pipeline.spine.place         # coords -> municipality, resumable
.venv/bin/python -m pipeline.spine.build_spine   # merge -> venues.geojson
.venv/bin/python -m pipeline.spine.spotcheck     # coverage gate
cp pipeline/output/venues.geojson console/public/data/
```

Every response is cached in `pipeline/raw/` and logged to `pipeline/output/request_log.jsonl`,
so a rerun costs nothing and any row can be traced to the bytes it came from.

### `city` came from the wrong rung of a chain

The spine read `city` from Wikidata's `wdt:P131` ("located in the administrative territorial
entity") one level deep and unfiltered. P131 is a **chain** — venue → village → town → county
→ state — and which rung a given item points at is an editorial accident of whoever wrote it.
So the same query returned a municipality for some venues and a state for others, with nothing
downstream able to tell them apart. **2,480 of 6,884 mapped venues (36.0%) held their own
state's name in `city`.** The US Coast Guard Academy's city was "Connecticut".

That is worse than a blank. A blank is a gap a reader can see; "Connecticut" is a wrong answer
wearing the costume of a right one, and it silently broke every join and filter that touched
it — the federal award join lost real matches to it, and the console's place filter had to be
built on `state` because `city` could not be trusted.

The fix does not go back to Wikidata. Constraining the SPARQL to municipality-typed items means
enumerating what counts as a municipality across fifty states, and the answer would still only
be as good as each item's `P31`. **The venue's coordinate is better evidence than its metadata**,
and the Census answers "what municipality is this point in" authoritatively, keyless, from the
same endpoint the ZCTA join already uses. Two layers, in order:

| layer | what it is | venues |
|---|---|---:|
| Incorporated Places | legal municipalities | 5,123 |
| Census Designated Places | populated but unincorporated — "Pepperdine University CDP" | 644 |
| *(neither)* | outside both — a racetrack in open country, a resort on national forest | 1,117 |

**County Subdivisions is deliberately not a third fallback**, even though it answers for almost
every remaining point. What it answers is not a city name: on a 60-venue sample it returned
"District 3, Worton (Betterton)", "Billings CCD", "District E" and "Canteen township". Falling
back to it would have taken coverage from 84% to 100% while re-contaminating the field with a
new kind of wrong string — the exact mistake being repaired. Those 1,117 get `None` and read as
unknown.

Result: **2,480 wrong → 0.** The 134 mapped venues whose city still equals a state name are
almost entirely New York, NY, which is correct. Every venue carries `city_source`
(`incorporated_places` / `census_designated_places` / `no_place`, or `wikidata_unverified` for
the 325 with no coordinate to geocode), so a Census-confirmed city is distinguishable from a
leftover one rather than being taken on faith.

The new field paid for itself immediately by making two unrelated errors visible: Cardinal
Stadium sits at 38.94/−77.00 (Washington DC) but carries `state = WA` from a bad Wikidata row,
and Four Seasons Arena — actually in Great Falls, Montana — carries a Manhattan coordinate.
Both are recorded here rather than patched, because each is a single upstream row and a special
case for either would be a rule fitted to one venue.

## Spine coverage (the gate)

`spotcheck.py` tests the spine against a hand-written list of every MLB park 2004–2024 —
a list that deliberately does not come from the source being tested.

- **70/77 matched (91%)**; 4 of the 7 misses are non-US venues, so US recall is ~96%.
- **6/8 former names** resolve to the current record (Enron Field → Daikin Park,
  Miller Park → American Family Field, Pacific Bell Park → Oracle Park).

Eight real bugs surfaced by these gates, all now fixed:

1. **Type-based census was incomplete.** American Family Field is typed "architectural
   structure" on Wikidata, so the `P31/P279* sports venue` walk never reached it. A second
   census pass on `P115` (home venue of a team) adds 439 venues that typing missed.
2. **Packed alias strings.** OSM's `old_name` for Hard Rock Stadium is one string:
   `"Pro Player Stadium, Dolphin Stadium, Sun Life Stadium"`. Now split.
3. **Full legal names only.** Wikidata says "Angel Stadium of Anaheim"; newspapers say
   "Angel Stadium". Locative tails are now also registered as match keys.

The last two were surfaced by step 2, when the gold-set loader tried to resolve venue
names a human typed from memory — the same shape of input the extractor will face:

4. **Person-named buildings were unreachable.** "Jacob K. Javits Convention Center" had
   exactly one match key: its full legal name. No reporter writes that; they write "the
   Javits Center". Surnames (and their `X Center` contraction) are now keys too, reached by
   requiring a middle initial so the rule cannot fire on "Los Angeles Memorial Coliseum".
   204 venues gained a surname key, 15 of them convention centers.
5. **Accents were dropped, not folded.** Wikidata spells it "Henry B. González Convention
   Center", which normalized to `gonz lez`; US wire copy spells it "Gonzalez", which
   normalized to `gonzalez`. The two could never meet. `match_key` now folds via NFKD.

The last three were surfaced by the extraction candidate finder — the first thing to scan
the match keys against running prose rather than against a single typed name:

6. **Category nouns matched half the corpus.** Stripping locative tails turned "The Ballpark
   at Hallsville" into the key `ballpark`, which six venues then owned; splitting packed
   aliases turned "Water World, Colorado" into `colorado` and "Ciber Field, Denver" into
   `denver`. A test article about Coors Field returned 14 candidates, 11 of them noise.
   `usable_key` now drops any derived key made only of category nouns, and any key equal to
   a city or state the spine already knows about. 198 keys dropped, spot-check unchanged.
   A venue whose *canonical* name is a pure category — an OSM way really is labelled
   "Convention Center" — keeps the key, but `build_index` refuses to search on it, so the
   record stays reachable by id without attaching itself to every article that mentions a
   convention center.

   **The first version of this fix overcorrected**, and the audit that caught it is worth
   keeping: counting how many venues the text scan can no longer reach at all. It was 63
   in-scope venues, including Fair Park and 21 Memorial Stadiums, because the word list
   mixed category nouns (*stadium*, *arena*) with qualifiers (*memorial*, *civic*, *fair*,
   *university*). Prose says "the ballpark"; it never says "the memorial stadium". Only
   category nouns belong in `VENUE_TYPE_WORDS`, and the count is now 22 — all of them
   venues genuinely named "Expo Hall" or "The Forum". `ball` came out for a blunter reason:
   Ball Arena is the old Pepsi Center, and listing it deleted Denver's biggest venue.
7. **11 US cities were in the spine as venues.** Boston (`wd-Q100`), Chicago, New York City,
   Los Angeles, Baltimore, Atlanta, Portland, Spokane, Sacramento, Shreveport and
   Burlingame, plus Weber County and a few neighborhoods. They came in through bug #1's fix:
   `P115` (home venue of a team) sometimes names the city rather than the building. An
   article with a Chicago dateline was being offered "Chicago" as a candidate venue, which
   is a wrong foreign key on a real event — worse than no key at all. `is_settlement` tests
   the `P31` labels, not the name, and only rejects a record when *every* label says
   settlement: Fair Park, Park City, Jackson Park and Taos Ski Valley are real venues whose
   names are places, and the US Naval Academy is genuinely typed both a census-designated
   place and a naval academy. 17 records dropped, 0 false positives across 7,261, kept in
   `spine_settlements_rejected.json` rather than silently eaten.
8. **Convention centers were unreachable by their printed names.** These have the widest
   gap between the name on the deed and the name in the paper, because the legal name
   absorbs every function the building serves. Sacramento's is the "Sacramento Convention
   Center *Complex*"; Tacoma's is the "*Greater* Tacoma Convention *and Trade* Center";
   St. Louis's is the "America's Center Convention Complex", which a reporter only ever
   calls "America's Center". None of them matched. `convention_forms` collapses those tails,
   adding 24 keys across 20 venues. Every rule is anchored to an explicit convention
   phrase — an earlier draft stripped a leading "Greater " unconditionally and turned
   "Greater Nevada Field", a credit union's naming-rights deal, into a ballpark that does
   not exist.

Known remaining gaps, deliberately left open:
- 297 ambiguous match keys. City/state is **not** always enough — the three Madison Square
  Gardens are all in Manhattan, NY. `resolve_venue` therefore takes an optional year and
  narrows on the venue's operating window (the 1925 Garden closed in 1968, so a 2005
  contract cannot be about it). Where dates are missing it returns `ambiguous` rather than
  guessing.
- 610 venues without coordinates; they stay in the spine but cannot be mapped.
- Non-US venues (Rogers Centre, Estadio de Béisbol Monterrey) are out of the census scope.
- 22 in-scope venues are unreachable by text scan because their names really are category
  phrases — "Expo Hall", "Convention Center", "The Forum", "Stadium Bowl". They keep their
  `venue_id` and can still be assigned by hand.
- Case-sensitive nickname keys assume the article preserves case. Some Nexis and ProQuest
  exports are all-caps, which would erase the signal and let `pond`, `barn` and `cell` fire
  freely. Untestable until the USB samples arrive, so no mitigation has been guessed at.
- Title Case headlines capitalize every word, so a nickname key can match on a headline that
  was not naming a venue. Rarer than the all-caps case and self-limiting: the body usually
  either confirms the venue or gives the model nothing to attach an event to.

## Schemas and the gold set (build order 2)

`pipeline/schema.py` is the single definition of every record type — contract event, tenure
record, hunt log, federal award, ACS context. The extraction prompt's JSON schema is
*generated* from the same field list the validator reads, so the prompt and the validator
cannot drift apart.

```bash
.venv/bin/python -m pipeline.spans.gold        # load + validate the workbook, resolve venue_ids
.venv/bin/python -m pipeline.spans.evaluate    # the eval gate (recall vs. the gold rows)
.venv/bin/python -m pipeline.spans.seed "Coors Field" "Madison Square Garden | 2005"
```

- **The workbook never grows a column.** Kiki's README forbids ad-hoc columns, so
  `venue_id`, `tenure_id`, `operator_normalized` and `derived_from` are derived on load
  instead of stored. Her 16 columns are what round-trips.
- **Two venue vocabularies, on purpose.** The spine calls Coors Field a `ballpark`; the
  workbook dropdown calls it a `stadium`. `venue_id` is the join; the type strings are
  never compared directly.
- **Renames, sub-brands and acquisitions are three different things.** ARA Services *is*
  Aramark (rename → normalize). Levy is a Compass division (sub-brand → normalize, keep the
  division). Centerplate was *bought by* Sodexo in 2017 (acquisition → **never** normalized;
  a 2005 Centerplate contract was not a Sodexo contract, and folding it in would invent a
  Sodexo run no article reports).
- **`seed.py` fills in the transcription, not the judgment.** Given venue names it emits the
  workbook's 16 columns with name/city/state/coordinates from the spine and the contract
  facts blank. `end_status` is left blank deliberately: `ongoing` is an assertion and
  `unknown` is an admission, so a default would silently turn one into the other.
- **The gold rows themselves are Kiki's to write.** An eval set produced by the author of
  the system it grades measures nothing — the same reason `spotcheck.py` uses a
  hand-written MLB list rather than the source under test.

## Extraction (build order 3)

```bash
.venv/bin/python -m pipeline.extract.prompt      # print the rendered prompt for a sample article
```

`pipeline/extract/` is written but has never seen a real article. Two files:

- **`candidates.py`** narrows the spine before the model sees it. 7,494 venues and ~11,200
  match keys do not fit in a prompt, and a model asked to pick from 7,494 options picks
  badly. Matching is token-based, not substring-based — "Gardens" must not match "Garden" —
  and each key is triggered by its *rarest* token, so "madison square garden" is looked up
  under `madison`, not under `garden`. Building the index takes 0.07s; scanning an article
  takes about 1ms. When a name is shared, ties break on **capacity**: 30 venues own the key
  "memorial stadium", and truncating that list alphabetically at `MAX_CANDIDATES` dropped
  Minneapolis's 56,000-seat one while keeping a 6,516-seat one.

  113 searchable keys are also ordinary English words, and they are **matched
  case-sensitively**. This started as a note to build a stoplist, which turned out to be
  exactly wrong: `pond` is the Honda Center, `jake` is Progressive Field, `cell` is Comiskey,
  `igloo` is the Civic Arena, and `swamp`, `horseshoe`, `brickyard` and `birdland` are all
  real venues. Those are the names reporters use, so a stoplist would have deleted the best
  keys in the spine to remove noise. What actually separates the two uses is the capital
  letter a newspaper gives a name — "the Pond" versus "a pond" — so `build_spine` flags keys
  that appear in the system word list and `appears_capitalized` requires a proper-noun
  printing. Sentence-initial occurrences do not count, since every sentence capitalizes its
  first word.
- **`prompt.py`** is the prompt itself, plus `validate_extraction`.

Three things the model is not trusted with:

- **`venue_id` cannot be hallucinated.** The model never sees the spine — only the handful
  of candidates the text scan produced — and `validate_extraction` re-checks that every id
  it returned was on that list. Same for the source fields: `source_date` and friends are
  copied from the article header and compared afterwards, because a quietly rewritten
  provenance field passes every type check.
- **The operator crosswalk is rendered into the prompt from `schema.py`.** Add a sub-brand
  to `SUB_BRANDS` and the prompt changes with it. `normalize_operator` still runs over the
  answer and wins.
- **The response schema is `event_json_schema()`**, generated from the same `EVENT_FIELDS`
  the validator reads.

The hardest instruction in the prompt is the one about RFPs. Trade press writes "Aramark is
expected to be awarded" in the same register as an actual award, and a model rewarded for
finding things will turn both into `won`. A phantom win is worse than a missed one: a miss
leaves a gap the hunt log can record, while a phantom fabricates a span that never existed.
Dates get the same treatment — the event date is when the contract takes effect, never the
publication date used to fill a hole.

Candidates carry `plausible_at_article_date` as a **flag, not a filter**. A 2005 article can
legitimately discuss a stadium demolished in 1968; dropping the candidate would force the
model to invent one. Flagging lets it weigh them, and lets the reviewer spot a bad pick.

## Ingest (build order 4)

```bash
.venv/bin/python -m pipeline.ingest.collect /Volumes/USB/articles --label usb1 --dry-run
.venv/bin/python -m pipeline.ingest.collect /Volumes/USB/articles --label usb1
.venv/bin/python -m pipeline.ingest.run --show 3
```

Four modules, and the USB is treated as read-only evidence throughout — nothing here opens
a file for writing on the source volume, so a bad run is always recoverable by re-running
against a drive that was never touched.

- **`collect.py`** copies article files into `articles/raw/<label>/`, keeping the original
  relative path so `source_file` in an event points at a file a person can open. Every file
  is sha256'd; identical bytes are recorded as duplicates rather than parsed twice (exports
  get re-run and re-saved constantly). Unhandled extensions are listed as *skipped*, not
  ignored — a `.doc` full of articles that nobody noticed is a hole in the corpus.
- **`formats.py`** is the only place that knows about file formats: one file in, plain text
  out, for `.txt/.html/.rtf/.pdf/.docx`. Encoding order is `utf-8-sig, utf-8, cp1252,
  latin-1` — Nexis and ProQuest `.txt` exports are usually Windows-1252, and decoding
  cp1252 as latin-1 turns a smart quote into `â€™` which then gets stored as an article's
  headline. Non-breaking spaces are converted to real spaces because Nexis puts U+00A0
  between the month and the day, which makes "March 3, 2005" match no date parser.
  A scanned PDF with no text layer raises rather than returning `""` — saying so beats
  handing the extractor an empty body and calling the article processed.
- **`parse.py`** splits concatenated exports and reads the headers. Both vendor layouts are
  handled: Nexis classic (`3 of 25 DOCUMENTS`, ALL-CAPS labels) and ProQuest / Nexis Uni
  (`Document 3 of 2`, Title-Case labels, `End of Document`). Anything unrecognized becomes
  a single article with whatever the header scan found — never dropped, never invented.
- **`run.py`** parses everything under `articles/raw/` into `output/articles.json` and
  prints the gate.

The gate is unflattering on purpose. Ingest is the stage where failure is *invisible*: a
splitter that merges two articles, or a header reader that swallows the first paragraph,
still produces a clean file with a plausible row count. So the numbers reported are the
ones that catch that:

| Number | What it catches |
|---|---|
| `text retained` | chars inside some article ÷ chars in the file — a splitter throwing articles away |
| `body share` | chars in `body_text` ÷ chars in the file — header parsing eating the article |
| `usable` | articles with all provenance fields *and* a non-empty body |
| `missing source_date` etc. | `schema.py` requires all four source fields, so an article missing one can yield **no valid events at all** |

The fixture corpus this was originally measured against — synthetic Nexis-classic,
Nexis-Uni, ProQuest, HTML, RTF and DOCX exports, reported here as 6/6 usable, 99.0% text
retained, 71.2% body share — **is not in the repository and those numbers cannot currently
be reproduced.** They are left in place as a record of what was measured, not as a claim
anyone can check today. The corpus that *is* checked in is `pipeline/fixtures/usb/`, and the
numbers it produces are printed by the dress rehearsal below: **6 articles, 4 usable, 96.8%
text retained, 62.2% body share.**

**Read those two percentages as measurements of prose I wrote, not of journalism.** The
fixture articles are invented, so text-retained and body-share describe how much of *my
imitation* of a Nexis export survives the parser. They are reproducible, which the older
numbers are not, and they are the right shape to watch for regressions — but they are not
evidence about real exports, and neither number should be quoted as one. The first real
export off the USB replaces them. Same caution applies to the parser findings recorded
under [Dress rehearsal](#dress-rehearsal-end-to-end-on-a-fake-usb).

The four bugs the original fixtures caught before any real data did are real and the fixes
are in the code:

- `"|".join(MONTHS) + "[a-z]*"` binds the suffix to **December alone**, so every
  spelled-out month failed and only abbreviated dates parsed. Half the corpus would have
  had no `source_date` and therefore produced zero events.
- Nexis `DATELINE:` holds a *place* (`DENVER`), not a date. Reading it as a date label cost
  every classic-format article its publication date.
- ProQuest prints its citation block **below** the full text, so a header scan that stops
  at the body never sees `Publication title:` — and then the positional fallback assigns
  the headline to `source_publication`.
- ProQuest also puts the article on the same line as its label (`Full text: Aramark…`), so
  the body has to start at the label's *value*, not the next line.

Provenance is never fabricated. `source_date` is not guessed from file mtime, a month with
no day (`March 2005`) is reported as incomplete rather than filled in as the 1st, and an
article with no readable header keeps three nulls and three entries in `problems`. A
corrupt file is a line in the report, not a stack trace that loses the other 1,999.

### The first real export (2026-08-12)

The USB arrived. It carries four article files — two ProQuest RTF exports (Sodexo 241 MB,
Aramark 758 MB) and two EBSCO `.docx` — plus four `.xls` financial workbooks that `collect`
correctly lists as *skipped* rather than silently ignoring. **600 documents.**

It broke the ingest in three places, and every one of them failed silently. That is the
failure mode this stage was built to expose, and it took real data to expose it:

**1. 99% of the drive is binary, and it ate the articles.** ProQuest inlines page scans with
RTF's `\binN` — 745 MB of the Aramark file and 239 MB of the Sodexo one is PNG. A PNG
contains `{` and `}` bytes, striprtf counts those as RTF group delimiters, and one 5.6 MB
scan carries **6,981 more closing braces than opening ones**. The group depth goes negative,
striprtf concludes the document ended, and it returns what it has — mid-file, without
raising. Measured: the old `from_rtf` recovered **1 of 100** articles from Sodexo and **6 of
500** from Aramark. It reported no error either time. `strip_bin` now skips each payload by
its own declared length, which is what the length is for, and all 600 come back.

**2. The layout is a third one, and it numbers nothing.** `DOC_START` looks for
`3 of 25 DOCUMENTS` or `Document 3 of 25`. Across 600 real documents those appear **zero
times**. ProQuest's RTF export separates records with a `ProQuest document link` line under
the headline instead — a string `BODY_TAIL` already knew, from the other end of the problem.
Without it the whole export parsed as *one* article: 4 files → 4 articles, body share 2.7%.
The split cannot be made at the link line, because the headline and byline sit above it, and
it cannot be made at the blank line above either, because a page scan is filed with a
headline and no byline. What is uniform is the previous record's citation block, whose
fields are all `|`-delimited, so that is the edge. 600 blocks, every one with a headline
line, **100.0% of the text inside a block**.

**3. `FULL TEXT` is a bare label.** ProQuest writes it alone on a line, with no colon, so
the labelled-header scan never saw it and `body_at` stayed 0 on all 600 documents. The body
then fell back to the whole block and `BODY_TAIL` cut it at the link line — which in *this*
layout is at the top of the record, not the bottom. Median body: **28 characters**. With
`FULL TEXT` and a bare `DETAILS` both recognised, body share went 2.7% → **79.2%** and the
median body 28 → **2,508**.

| | before | after |
|---|---|---|
| articles found | 4 | **602** |
| usable | 2 | **349** |
| text retained | 100.0% | 100.0% |
| body share | 2.7% | **79.2%** |
| median body chars | 44,103 | 2,508 |

The median body *falls* because the before-column had four articles in it, each one an
entire export glued together.

**A third of the corpus is not text, and it now says so.** 236 of the 600 documents are page
scans: ProQuest supplies a date-and-page line where the headline goes, opens a full-text
section, and closes it without a word. 224 of them carry the page image, 12 come with
nothing at all. The signal is exact — every one of the 600 declared a full-text section and
precisely the 236 empty ones supplied none, no false positives either way — so those records
now report *citation only: export declared a full-text section and supplied none (page scan
— text is in an image, needs OCR)* instead of `empty body`. Calling it an empty body would
read as a bug in the parser and hide a third of the corpus behind it. **The real corpus is
366 readable articles, not 600**, and that is the number to plan extraction around.

**Compass has no articles on this drive.** Its two EBSCO `.docx` are metadata exports — 100
numbered records, 89 abstracts, and **zero full text** between them. They parse as two
citation lists rather than two hundred articles, which is what they are, and because neither
carries a publication or a date the schema already refuses them: they cannot produce an event
no matter what the extractor is handed. So the readable corpus is **Aramark and Sodexo only**.
Compass is a hole in the coverage, and it is the kind that would otherwise show up on the map
as an operator that simply never won anything.

**The two parser findings below are still unchecked.** Both concern Nexis-classic blocks with
bare centered lines. This export is ProQuest RTF, which labels its headers, so it did not
exercise either one. They stay recorded and unfixed.

## Extraction (Phase 1.5 — the only stage that *generates* data)

```bash
.venv/bin/python -m pipeline.extract.check_run       # the gate — runs today, no key needed
.venv/bin/python -m pipeline.extract.run --dry-run   # every prompt built, nothing spent
.venv/bin/python -m pipeline.extract.run --limit 5   # a real trial before the full corpus
.venv/bin/python -m pipeline.extract.run             # articles.json -> contract_events.json
```

Every other stage fetches or derives; this one asks a model and gets prose back. It is the
only place in the pipeline where a clean-looking output file can be **entirely invented**,
so the runner is built to disbelieve the answer:

| The model returns | The runner does | Why that is the right call |
|---|---|---|
| a `venue_id` never offered as a candidate | nulls it, sets `needs_review`, **counts it** | an id that was not on the list cannot be right; the count is the drift alarm |
| a rewritten `source_publication` | restores it from the article record | the article is the authority; the model was only asked to copy |
| `Centerplate` normalized to `Sodexo` | refuses — Centerplate stays Centerplate | a 2005 Centerplate contract was not a Sodexo contract |
| `date_precision: year` on `2005-06-15` | **rejects the row** | which of the two is wrong is a judgement call, so a person makes it |
| an operator the crosswalk lacks | keeps it, flags it | a flagged row gets resolved; a dropped one is invisible |
| zero events | accepts it | most articles that name a caterer report no contract event |

Rejected rows go to `output/extract_rejected.json` with their problems attached — never
dropped. `contract_events.json` stays schema-clean because `spans.pair` reads it.

**Resumability is the payload-hash cache in `PoliteSession`, not bookkeeping.** An
interrupted run re-reads what it already paid for and spends only on the rest; a finished
run can be replayed with no API key at all, because every response is on disk under
`raw/extract/`. Change the prompt and every hash changes, which is correct — a cached answer
to a different question is not an answer.

### What is and is not verified

`check_run.py` seeds that cache with hand-written answers that are wrong in specific ways
and drives the **real** `run()` loop over them — real prompt, real candidate finder, real
repairs, real validation, no network. 17/17 pass, and its output feeds `spans.pair` at 5
events in / 5 paired / 0 unusable / 0 unaccounted.

The two ways a 500-article run wastes a night were verified against a local mock server,
because "it stops early on a bad key" is worth more than an assertion:

- **401 → stops at article 1/10**, named as configuration rather than content.
- **unreachable host → stops at article 3/10** via `FATAL_STREAK`. This one needed the
  count: `PoliteSession` catches connection errors into its retry loop and re-raises them
  as `RuntimeError`, the same type an article the model keeps truncating produces, so the
  exception type alone cannot tell a broken endpoint from a bad article. Checking only the
  type would have ground through all 500.

The endpoint itself is no longer unverified — see **The first real calls (2026-08-12)** below.
Request construction, backoff and cost accounting have now round-tripped against Anthropic on
15 real articles. What is still unverified is the corpus run: 366 articles have never been
extracted, and no gold row has been scored against a real extraction.

### The first real calls (2026-08-12)

15 articles, real endpoint, `claude-opus-4-6`. Zero failed calls, zero rejected events, zero
`venue_id not offered` repairs — the model never invented a venue. Two defects surfaced that
only a real, *repeated* call could show.

**1. The response cache could never hit, so no run was ever resumable.** `run.py` promises
that "an interrupted run re-reads the calls it already paid for". It did not. Two consecutive
runs over the same 5 articles shared **0 cache entries and were billed twice**. The cache key
is a hash of the payload, and one line of the payload was not stable: `Known parents:` in
`prompt.py` was rendering `KNOWN_OPERATORS`, a `set`, without `sorted()`. Python randomizes
string hashing per process, so the operator list came out in a different order on every run —
same prompt meaning, different bytes, different hash, guaranteed miss. Every other list in
that function was already sorted; this one was missed. Fixed and verified: the payload hash is
now identical across three separate processes, and a repeat 10-article run reports
**cache hits 10/10, 0.0s, no new spend**.

This mattered more than the money. A two-hour corpus run that is interrupted at article 300
would have had to be paid for again from the top, every time.

**2. Prompt caching never engaged at all — the block comment in `build_payload` is wrong.**
`cache_control` is set on the system block and the tool schema, and the API silently ignored
both: every call reported `cache_creation_input_tokens: 0` and `cache_read_input_tokens: 0`.
It is not the header, the API version, the key, or the block layout — a synthetic 9,903-token
system block on the same key caches fine. It is a **minimum size**. Measured by bisection
against the live endpoint:

| cacheable prefix | cached? |
|---|---|
| 2,210 tokens | no |
| 3,310 tokens | no |
| 4,190 tokens | **yes** |

The threshold is 4,096 tokens for this model. Counted exactly: system 2,499 + tool schema
1,261 = **3,760** — 336 tokens short. The article body sits after the breakpoint and varies per
article, so it cannot make up the difference.

The honest consequence is a cost line, not a bug: the corpus costs **$18.22** rather than the
$12.05 it would cost if the prefix cached, a **$6.17** difference. That is left alone
deliberately. Padding the prompt with 336 tokens of filler to cross a billing threshold would
change what the model reads in order to save six dollars, and the prompt is the one artefact
in this pipeline whose exact wording has been tuned against the gold set. The
`cache_control` markers stay where they are: they cost nothing, and they start working the day
the schema or crosswalk grows past the threshold on its own.

**3. The venue join works, and the first five articles were a misleading sample.** The initial
`--limit 5` returned 5 events with **0 venue matches**, which reads like a broken join. It was
not. `--limit 5` takes the first five articles in file order, and those happened to be prison
and county-jail contracts — `El Paso County Criminal Justice Center`, `Michigan Department of
Corrections`. The spine holds 7,494 sports and leisure venues and **zero** correctional
facilities, so a null `venue_id` was the correct answer, and the model said so in `notes`
rather than forcing a match. That is the behaviour the prompt asks for, confirmed on real data.

Re-running with five articles chosen for venue vocabulary matched immediately:
`U.S. Bank Stadium` → `wd-Q7929512`, Minneapolis MN, twice, from two different papers. The
chain from RTF on a USB stick to a mapped point is now closed end to end on real data.

The reason it needed checking is that the corpus is not mostly about the venues the spine
covers. Measured across all 366 readable articles by domain vocabulary:

| dominant domain | articles | share |
|---|---|---|
| higher ed | 120 | 32.8% |
| K-12 schools | 92 | 25.1% |
| **stadiums / arenas / convention centers** | **71** | **19.4%** |
| healthcare | 33 | 9.0% |
| none of these | 29 | 7.9% |
| corrections | 21 | 5.7% |

So roughly **19% of the corpus is on-scope for this spine**, and a large majority of extracted
events should be expected to carry a null `venue_id`. That is a fact about a search that
returned every Aramark and Sodexo contract story rather than only venue ones — not a defect,
and not something to fix by widening the spine two days out. It does mean the corpus run
should be judged on *venue-matched* events, not on total events.

### The 30-article sample (2026-08-12)

A random sample of 30 of the 366 readable articles, `random.seed(20260812)` so it is exactly
reproducible. Unbiased on purpose — picking articles by venue vocabulary would have measured
the sampler rather than the corpus. Result: **16 valid events from 30 articles, 1 carrying a
`venue_id`.** 16 of 30 articles (53%) produced no event at all, which is the prompt behaving
as instructed rather than failing.

The one venue-matched event is a genuine find, and it is the hard case working:
`Memorial Stadium` → **Gies Memorial Stadium, Champaign IL**, Sodexo, 2015. About 30 venues
share the key "memorial stadium"; the model picked Champaign because the News-Gazette is a
Champaign paper and the article quotes the University of Illinois athletics concessions
director, and it wrote that reasoning into `notes`. That is the disambiguation `candidates.py`
was built for, confirmed on real data.

**The finding: a union contract is not a concessions contract.** The sample's other
venue-matched event was Aramark / `expired` / 2016-04-01 at Citizens Bank Park, from an
article about a Unite Here Local 274 picket. The source sentence is "the union's contract with
Aramark expired April 1" — a collective bargaining agreement. Aramark's concessions contract
was never mentioned, and Aramark still runs that ballpark.

`expired` is in `CLOSERS` in `spans/pair.py`, so this row would have closed Aramark's tenure
span and drawn on the map that Aramark left Citizens Bank Park in April 2016. A false fact,
rendered as confidently as a true one, from an article that says no such thing.

What makes it worth writing down is that **the model was not wrong — the schema was**. It put
the right answer in `notes`: *"this is the labor/union contract expiration, not the food-service
concession contract... flagging for review."* It understood the distinction, had no
`event_type` that expressed it, and picked the closest one. `needs_review` was already true,
but review catches a row a human reads; it does not stop the row reaching `pair.py`.

The `## What is NOT an event` list in `prompt.py` now excludes labor contracts explicitly, and
scopes `strike` to workers actually striking rather than picketing, contract talks or a strike
vote. Re-asked, that article returns **zero events**. Re-running all 30 confirmed no real event
was suppressed elsewhere: the Memorial Stadium find survives.

This is the argument for a gold set in one example. The defect was invisible to every gate —
schema-valid, correctly typed, high confidence, honestly annotated — and visible in about a
minute to anyone who read the article next to the row.

One operational note: **editing the prompt invalidates the entire response cache**, since the
system block is part of the payload hash. The 30-article re-run cost the full $1.04 again.
Prompt changes are therefore corpus-run-priced, and should be batched before the full run
rather than made after it.

### How long the corpus will take

Measured here: `build_index()` 0.08s once, candidate finding **0.4–1.4 ms/article** (all 500
in under a second). Everything local is free; the model call is the whole clock.

These are no longer estimates. Measured over 15 real calls: **8.1–12.5s per article**,
**8,252 input + 340 output tokens per article** on average, **$0.050 per article**, no
caching (see above). For the 366-article corpus that projects to:

| | measured basis | 366 articles |
|---|---|---|
| wall clock | 8.1–12.5 s/article | **50–76 minutes** |
| input tokens | 8,252/article | 3.02 M |
| cost | $0.050/article | **$18.22** |

Both are inside the original $10–20 / ~2h guess, so nothing downstream needs rethinking — but
the guess was right for the wrong reason, since it assumed a prompt cache that never engaged.

**What it actually cost (2026-08-13): $12.85 and 29 minutes**, against the $18.22 projected
here. The projection was not wrong arithmetic, it was the wrong sample — the 15 probe articles
had a median body of 9,666 characters against the corpus median of 4,278, so it extrapolated
from unusually long articles. The lesson is the one this table was supposed to teach and
did not: a per-article rate measured on a non-random sample is a rate for that sample. Per
article the real figure is **≈3.5¢**.

Runs are sequential on purpose, and now that the payload hash is stable the cache genuinely
makes a re-run free — verified at 10/10 hits, 0.0s. That beats a concurrent runner whose
failure mode is a half-written output file. The runner prints its own rate and ETA every 25
articles and reports actual tokens and cost at the end.

`PRICE_PER_MTOK` in `extract/run.py` is a hardcoded rate with the date it was checked
printed next to the total, so a stale rate is visible rather than quietly wrong.

## Span pairing (Phase 1.6 — "the actual engineering problem")

```bash
.venv/bin/python -m pipeline.spans.check_rules      # the gate — runs today, no data needed
.venv/bin/python -m pipeline.spans.pair             # events -> output/tenure_records.json
.venv/bin/python -m pipeline.spans.pair --events fixture.json --out /tmp/t.json   # try a fixture
```

An article reports a moment: "Aramark won the Coors Field contract in 2004." The tenure
table wants a **run**: Aramark held Coors Field from 2004 to 2011. No article says that.
`spans/pair.py` produces it by putting every event about one operator at one venue on a
timeline and reading the shape.

| Event | Effect |
|---|---|
| `won` | opens a span |
| `renewed` | extends an open span; opens one with an **unknown start** if none is open |
| `lost` / `expired` / `self_op` | closes the open span; with none open, yields a run whose end we can see and whose start we cannot |
| `strike` / `violation` / `initiative` | **presence, not contract.** Never opens or closes, but a strike against Aramark in 2008 proves Aramark was there in 2008 |

Three distinctions the pairer refuses to collapse:

- **`ongoing` is not `unknown`.** An open span means one of two opposite things: they still
  hold it, or we never found the end. A span is `ongoing` only when its latest evidence is
  within `ONGOING_WINDOW_YEARS` (3) of `as_of`; otherwise `unknown`, with `known_through`
  recording how far the evidence actually reaches. The map paints `unknown` only that far,
  so a 1998 award with no follow-up does not silently claim the venue for thirty years.
- **An inferred end is not a reported end.** When a different operator wins a venue in 2016
  the previous run *did* end — but no article said so, and no article said why. That span
  gets `end_date` from the successor, `exit_mode="unknown"`, and
  `extras.end_inferred_from = "succession"`. Skipping the inference would paint two
  operators on one venue simultaneously, which is a different lie. The one case where the
  cause is not a guess is a `Self-operated` successor: that *is* `self_op_conversion`.
- **A duplicate report is not a second event.** Three papers covering one award produce
  three events; collapsing them (same type, within 45 days, finest date wins) is what keeps
  that from becoming three spans. All three `event_id`s stay in `derived_from`.

Everything the pairer cannot resolve becomes a flag rather than a silent choice: unknown
starts, undated events, spans whose venue never matched the spine, re-awards with no
reported end, and genuine overlaps (a prime concessionaire and a premium-dining operator
can both be real). Those land in `extras.review_reasons` for Kiki's monthly batch review.
Pipeline-only fields live in `extras` because `_check_fields` rejects unknown top-level
keys — the workbook does not grow columns.

**The gate is `check_rules.py`**: 18 hand-written timelines, one per rule, each stated as
events in and spans out, plus an accounting check that every event lands in exactly one
span or in `unusable_events`. Written the same way as `spine/spotcheck.py` — the answer key
is separate from the code under test. It currently passes 18/18 with zero schema problems,
and it was checked *by breaking the pairer*: widening the ongoing window to 100 years fails
6 scenarios, and letting the succession pass guess `lost_bid` instead of admitting
`unknown` fails 1. A gate that cannot fail is not a gate.

This is logic, not data — `check_rules.py` runs today with no articles. What it cannot tell
you is whether real reporting looks anything like these timelines. `spans/evaluate.py`
scores `tenure_records.json` against Kiki's workbook, and that is the number that counts.

## Emit (Phase 1.7)

```bash
.venv/bin/python -m pipeline.emit.records
cp pipeline/output/*.geojson console/public/data/
```

Six files, three audiences: the map (`*.geojson`), an auditor (`*.csv`), and Kiki
(`review_queue.csv`, `search_log.csv`). Two decisions live here because nothing upstream
can make them:

**How far a span gets painted.** `end_date` is only filled when a run actually `ended`.
Both `ongoing` and `unknown` runs have no end date — and they must not render the same way.
So each feature carries `render_end_year` plus `render_end_basis` saying where that year
came from:

| `end_status` | painted to | basis |
|---|---|---|
| `ended` | `end_date` | reported end |
| `ongoing` | today | still held as of last coverage |
| `unknown` | `known_through` | evidence stops here; the end is unknown |

That third row is the point. Without it, a 1998 award with no follow-up colors a venue
through 2026 and the map asserts twenty-eight years nobody reported. Years are emitted as
integers so the time slider is a numeric `setFilter`, not a string comparison.

**What is not on the map, and where it went instead.** A run whose venue never matched the
spine has no coordinates and cannot be a feature — it still goes in the CSV, and the count
prints. Same for features that can never satisfy the slider because they have no start year
or no evidence date. A row missing from the map has to be visible somewhere or it is just
lost.

`tenure_records.csv` leads with `WORKBOOK_TENURE_COLUMNS` in Kiki's exact order, then the
pipeline-derived fields, so a row can be checked against her sheet without re-ordering
anything.

**`review_queue.csv`** is one flat sheet covering all three record types — spans, events,
and articles that could not yield provenance — sorted by issue so a monthly sitting works
through one class of problem at a time. Each row puts what the pipeline produced next to a
260-character snippet centred on the venue name *as the article printed it*. A review queue
that makes someone open the source file to judge one row will not get used.

Building this exposed a flaw in the span pairer: it had been flagging every `unknown` end
for review, which put most of the table in the queue. An unknown end is the normal state of
a twenty-year corpus, not a decision anyone can make at a desk — it is already visible as
`end_status` + `known_through`, and what it actually calls for is another search, which is
what the hunt log is for. The flag was removed; the review queue now carries only rows a
human can resolve. On the end-to-end fixture that took it from 7 rows to 4, and
`needs_review` from 3 of 4 spans to 1 of 4.

`search_log.csv` is the hunt log verbatim, `nothing_found` rows included — a documented
silence is interpretable, an empty cell is not.

## Dress rehearsal (end to end, on a fake USB)

```bash
.venv/bin/python -m pipeline.check_end_to_end
```

Every stage had its own gate and all of them passed, but nothing had ever run them in
sequence — which hides a different class of bug: not "does this function work" but "does the
file this one writes match the file the next one reads". `pipeline/emit/` in particular had
**never processed a single row**; every file it had produced was empty, and it is the stage
that decides what the console actually draws.

`pipeline/fixtures/usb/` is a checked-in fake USB stick: Nexis classic, ProQuest and an HTML
clipping, plus the things that go wrong on a real one — a duplicate re-save under a
different name, a `.doc` nobody can read, a `.DS_Store`, an article with no headline, an
article with no date. Because it is in the repo, the ingest numbers above are reproducible
by anyone.

**36/36 pass.** The whole path, counted at every hop:

```
COLLECT  5 files on the stick -> 3 copied, 1 duplicate, 1 skipped
PARSE    3 files -> 6 articles (4 usable)  text retained 96.8%  body share 62.2%
EXTRACT  6 articles -> 6 events returned (5 kept, 1 rejected)  cache hits 6/6
PAIR     5 events -> 5 spans  (paired 5, unusable 0, unaccounted 0)
EMIT     5 spans -> 4 map features (1 without coordinates); review queue 8
```

**What is real here and what is not.** Collect, parse, pair and emit run unmodified. The
model's *answer* is a fixture, seeded into `PoliteSession`'s cache the way `check_run.py`
does it, because there is no API key here — everything around the call is real: real prompt,
real candidate finder, real repairs, real validation. **This proves the plumbing, not the
model.**

The corpus is built so that each row loses something different, and the check is that
whatever is lost is *written down* rather than dropped:

| What goes in | Where it comes out | Why |
|---|---|---|
| a re-saved copy of an export | `duplicates` in the manifest | same sha256, parsed once |
| a `.doc` | `skipped`, with the reason | a file nobody noticed is a hole in the corpus |
| an article with no headline | `extract_rejected.json` | `source_title` is required, so it can yield **no valid event** — a parse gap becomes a missing map feature, and that is visible |
| an article with no date | `review_queue.csv`, `record_type=article` | in front of a person, next to everything else needing one |
| a college dining contract | a tenure row with `venue_id: null` | no spine venue matched; it is in the CSV, not on the map, and counted |
| a run that ends with no award ever reported | a feature with `start_year: null` | it can never satisfy `start_year <= T`, so it is never drawn — counted as `unpaintable_no_start`, and the venue panel says so |

All three values of `render_end_basis` appear, which is what the third table in **Emit**
promises and nothing had previously demonstrated: Aramark's Busch run is closed at 2019 by
*succession* rather than by any article, Delaware North's 2019 run is painted only to 2019
because that is where the evidence stops, and Sodexo's 2024 Petco award is `ongoing` as of
the pinned `AS_OF = 2026-08-11`.

**Verified in the browser, then removed.** The rehearsal geojson was copied into
`console/public/data/`, and the console read it correctly with no changes: at 2015 the
sidebar derived "1 of 6,469 venues have an operator — Aramark 1", and the Busch Stadium
panel listed *Aramark 2005–2019, needs review, end reported · cause not reported · inferred
from the next operator*, *Delaware North 2019–2019?, evidence stops here*, *Delaware North
?–2005, lost the bid*, and then the line **"1 run above has no start date, so it is never
painted on the map — only listed here."** The synthetic files were deleted afterwards and
the console falls back to "No runs on record" — shipping fixture data as if it were real is
the exact failure this project is trying not to have.

**The safety guard, and why it runs in a `finally`.** The rehearsal redirects five modules'
path constants into `_rehearsal/`, which is precisely the kind of thing that silently
half-works: miss one constant and the run overwrites a deliverable. So every file under
`output/` and `articles/` is hashed before and after, and one changed byte fails the check.
This is not hypothetical — `spans/pair.py` really did overwrite `tenure_records.json` once.

Testing the guard by deliberately removing one redirection found a second bug **in the guard
itself**: emit wrote its six files into the real `output/` and the run then died two lines
later, so the check that would have reported the damage never ran. It now runs in a
`finally` and prints every modified path. Re-tested: it names all five clobbered files and
exits non-zero even though the run crashed.

### Two parser findings, not yet fixed

Both concern classic Nexis blocks with **no labelled headers** — bare centered lines. They
are recorded rather than fixed because the fixture is one I wrote, and changing the parser to
match my own invention would be fitting the code to a guess. **Check these against a real
export off the USB before touching `parse.py`:**

1. A headline printed *below* the date line is lost. `parse_block` handles headline-above-date
   (`at_date >= 2`) but for `at_date == 1` it takes the line above the date as the publication
   and never looks below it, so `source_title` comes back null — and a null `source_title`
   means the article can produce no valid events at all.
2. `body_share` is 62.2% against the 71.2% previously reported. Some of that is these
   fixtures having proportionally larger headers than the old ones, but it has not been
   attributed line by line.

## Tenure layer in the console

```bash
cp pipeline/output/tenure_records.geojson console/public/data/
```

The plan asks that "at slider time T, a venue shows the operator whose span contains T
(color by operator; gray = no known operator = visible absence)". That is one dot per
*venue*, but `tenure_records.geojson` is one row per *run* — so the console collapses runs
to venues and drives `circle-color` on the spine layer it already has. A second GL source
at identical coordinates would have meant duplicate click targets and a capacity join done
only to keep two radii from disagreeing.

The window painted is `start_year .. render_end_year`, so the pipeline's three end cases
carry straight through: a reported end stops at the end, an `ongoing` run runs to today,
and an `unknown` run stops at `known_through`. On the fixture, Fenway Park — awarded in
1998 and never mentioned again — is colored in 1998 and gray in 1999. A run with no start
year is never painted at all, and the venue panel says so rather than leaving it missing.

Two things had to be decided in the console because the year resolution is coarser than
the data:

- **A handoff is not a conflict.** Aramark lost Coors Field and Compass won it on the same
  day in March 2011, so at year resolution both cover 2011. The full dates are in the
  properties, so the tie is broken at day resolution and 2011 goes to Compass. Only runs
  whose date ranges genuinely intersect are drawn as contested — those are the ones the
  pairer flags, and the map should not overrule it by picking a winner.
- **The legend counts only what is drawn.** The first version counted a run at a Wrigley
  Field demolished in 1966, so the legend said four venues and the header said three. Both
  numbers now come from the same set of visible venue ids, and the header is summed from
  the legend rows rather than counted again.

Verified against a fixture of thirteen spans built from real spine `venue_id`s and run
through the real pairer and emitter, so what the browser loaded is what the pipeline would
produce. It found two bugs: the handoff-as-conflict case above, and a missing-file path
that reported a JSON parse error because the dev server's SPA fallback returns `index.html`
with a 200 rather than a 404. The layer stays `status: 'planned'` in the registry — the
wiring is done, the data is not.

## Federal awards (USAspending)

```bash
.venv/bin/python -m pipeline.federal.check_rules    # 27 checks over 9,672 real award rows
.venv/bin/python -m pipeline.federal.records        # -> geojson + operator profile + exclusions
cp pipeline/output/federal_venue_awards.geojson console/public/data/
cp pipeline/output/federal_operator_profile.json console/public/data/
```

The first real data in the project. 9,672 federal contract rows naming one of the four big
operators; 393 of them are food service, totalling **$5.0B in obligations**.

**Two layers, because the data is two different things.** 8 of the 393 awards name a venue
in the spine — $104,595 at three places — and those are the map layer. The other 385 have
real places of performance that this spine does not contain: federal food service happens on
Marine Corps posts and in VA hospitals, not in ballparks. So the $5.0B lives in a **panel
with no geography** rather than being spread across three dots, where it would be off by four
orders of magnitude and look authoritative. On the map, an award is drawn as a **ring around
the venue's existing dot**, never as a dot of its own — a federal award is a fact about a
place already on the map, and a second point would double the count.

**The venue join has three gates, and each was sabotage-tested.** Matching award descriptions
to venue names alone produced twelve hits, of which ten were wrong — "JOINT TASK FORCE"
matched a Nevada music venue called The Joint. So a name hit also has to agree on place, and
the matched name has to be one a source recorded. Removing any one gate breaks a different
invariant in `check_rules`:

| gate removed | what the join becomes |
|---|---|
| name | 133 awards at 136 venues |
| place | 26 awards at 13 venues |
| alias | 11 awards at 4 venues, **$53.2M** |

**The place gate is ZIP, not city, because `city` is contaminated.** It used to compare the
award's city against the spine's — but 35.9% of venues hold their own state's name in that
field, and the Coast Guard Academy's `city` is literally "Connecticut". So the check was
throwing away correct matches on the strength of a corrupt string. It now compares the
award's place-of-performance ZIP against the venue's ZCTA, which is derived from the venue's
coordinates rather than copied from a source. That recovers five awards the city rule was
silently rejecting, including three at the Merchant Marine Academy where USAspending says
"GREAT NECK" and the spine says "Kings Point" — postal name versus municipal name for the
same ZIP. There is no state clause alongside it: a ZIP determines its state, and adding one
would only exclude the 1,085 venues that carry no state at all.

**The alias gate is what keeps a $53.0M contract off one dot.** `match_keys` in the spine
deliberately holds fragments of compound names so newspaper prose has something to hit. For
prose that is right; for attributing a dollar figure it is too loose, because a fragment can
name a different and much larger thing. Without this gate the join takes in a Sodexo award
reading "NUTRITION CARE SERVICES AT WEST POINT, NY FORT STEWART, GA FORT LEONARD WOOD, MO
FORT RILEY, KS FORT IRWIN, CA …". Its place of performance genuinely is ZIP 65473 and the
spine genuinely has a venue there — but that venue is *Marine Corps Detachment, Fort Leonard
Wood* and the key that fired is `fort leonard wood`, the post it sits on. One obligation, six
Army posts, landing whole on one dot and becoming 99.7% of the map's federal total. The gate
is not free: it also drops a correct $45,674 award whose description said "THE WASHINGTON
CONVENTION CENTER" rather than the venue's full name. Losing $45,674 of real attribution to
refuse $53.0M of false attribution was the trade, made deliberately.

**Declining is the expected outcome, and that was checked too.** 358 of the 393 in-scope
awards name no venue at all — they read "MEALS", "FOOD SERVICES", "PICNIC LUNCH PROVIDED TO
EMPLOYEES". A deliberately loose substring sweep of 11,688 distinctive venue names over all
381 unmatched descriptions turned up 2 candidates, one of them probably a different building.
There is no large missed join hiding behind the small number. Each award on the panel carries
its PIID so a reader who does not trust the join can look it up.

**Scope is recorded, not filtered.** Every one of the 9,672 rows keeps `in_scope` and
`scope_reason` on the row and lands in `federal_exclusions.csv` if excluded. A pipeline that
drops rows leaves no way to ask why 9,279 of them went away.

## Wage & hour enforcement (DOL WHD)

```bash
.venv/bin/python -m pipeline.labor.load            # -> profile + per-case CSV, from the snapshot
.venv/bin/python -m pipeline.labor.load --refresh  # re-fetch the mirror first
.venv/bin/python -m pipeline.labor.check_rules     # 66 checks
cp pipeline/output/labor_whd_profile.json console/public/data/
```

840 candidate rows out of the Wage and Hour Division's WHISARD database; **231 are concluded
food-service cases against these operators, carrying $2,146,787 in back wages owed to 2,459
workers** between 2001 and 2024. Sodexo ($793K), Compass ($788K) and Aramark ($427K) are
almost all of it; 39 of the cases carry WHD's repeat-violator flag.

**It is not served by dol.gov, and the console says so.** DOL's own API requires a registered
key, so the data comes from `labordata.bunkum.us` — an independent Datasette rebuild of the
same public-domain records. The panel names that host rather than letting a reader assume the
federal government served it. The exact query, its row count and a SHA-256 of the response are
in `pipeline/raw/whd/manifest.json`.

**There is no venue layer, and that is the finding, not a gap in the work.** Every other money
layer here reaches a venue because something in the record names one — a federal award's
*description* does. WHISARD has no such field: it records the employer's establishment address
and nothing else. The only join available is ZIP, and measured on the real rows it put the 179
geocodable cases across **420 distinct venues**. One Raleigh ZIP produces nine NC State venues
for a single case. Even the 31.8% that came back unambiguous are unambiguous by coincidence —
one venue happening to sit in that ZIP — not by evidence. So `labor_wage_hour_venues` stays
`planned` with that number written into its registry entry, and `check_rules` fails if a
`venue` column ever appears in the case CSV.

**Substring matching on company names was the whole difficulty, and it was caught by measuring
before shipping.** The first pass used SQL `LIKE` against names derived from the operator
crosswalk. Three separate traps came out of it, each of which would have printed a large,
confident, wrong number under a real company's name:

| pattern | what it actually matched | damage |
|---|---|---|
| `%FOODA%` | 14 Foodarama/ShopRite supermarkets, a McDonald's franchisee | **$429,880** of penalties under Fooda's name; zero real Fooda |
| `%SPORT SERVICE%` | "tran**SPORT SERVICE**S" — 84 ambulance and trucking firms | **$2,187,898** vs Delaware North's real $4,648 — a 470× overstatement |
| `legends` | 25 local sports bars (Legends Patio Grill, Legends Smokehouse) | zero Legends Hospitality |

**Deriving the alias table from the operator list was itself the bug.** It injected the bare
canonical names — *Legends*, *Compass*, *Levy*, *Morrison*, *Canteen* — which are ordinary
English words. The table is now written out by hand, every alias chosen so it is safe as a
leading-token match, and only a `DISTINCTIVE` subset is allowed to match in the interior of a
name. Matching is on **whole tokens**, which is what defeats the transport trap: "Contract
Transport Services" tokenizes to `("contract","transport","services")` and never yields the
adjacent pair `("sport","service")`. All three traps are regression tests in `check_rules`
using the exact strings WHD recorded, alongside the cases that must still match —
"Metroplex SportService, Inc.", "Aramak Uniform And Apparel LLC" (WHD's own spelling).

**Rejection is the majority outcome and is reported on screen.** 493 of the 840 candidates are
other companies entirely — Compass Bank alone is 80 — and another 114 are these operators in a
different line of business, mostly janitorial. The panel leads with that ratio rather than the
dollar total, because a reader shown only the 231 survivors will assume the query was clean. It
was not; it was made clean. Nothing is silently dropped: every row keeps a `scope` of
`in_scope`, `excluded_other_line`, `excluded_remote_site` or `rejected_not_an_operator` in
`labor_whd_cases.csv`.

**The registry blurb is the one place a number is typed by a human, so the gate checks it.**
The panel derives everything it prints from the profile, but `layerRegistry.ts` is static
TypeScript and cannot. `check_console` in `check_rules` reads that file and asserts each figure
in it against the profile, and asserts the console's copy of the JSON is byte-identical to what
the pipeline emitted. Changing the blurb's "231" to "232" fails the gate.

## ACS neighbourhood context

```bash
.venv/bin/python -m pipeline.acs.geocode        # venue coords -> ZCTA, both vintages, resumable
.venv/bin/python -m pipeline.acs.check_rules    # 29 checks over 96,376 real venue-year rows
.venv/bin/python -m pipeline.acs.records        # -> acs_venue_context.{json,csv}
cp pipeline/output/acs_venue_context.json console/public/data/
```

Workers, median household income, transit share and long-commute share for the ZIP Code
Tabulation Area around each venue, 2011–2024. **6,831 of 6,884 mappable venues** get context
in at least one vintage, and the shortfalls are recorded rather than dropped:

| Venues | Coverage | Why |
|---|---|---|
| 6,804 | all fourteen years | resolved in both ZCTA vintages, both with published estimates |
| 27 | half the series | the coordinate falls in a ZCTA that exists in only one vintage (22 `2020_only`, 5 `2010_only`) |
| 37 | none | the coordinate is in no ZCTA at all — ZCTAs are built from addressed mail delivery, so water, piers and unaddressed land have none |
| 16 | none | the geocoder returned a ZCTA code that the ACS files have no row for |

That last row is a rule worth stating: a code with no data behind it is written out as
**blank**, not as the code. A populated `zcta` column with nulls beside it looks like a
successful join and is worse than an admitted gap.

**A ZCTA is not the venue, and the console says so on every panel.** It is a postal-delivery
area covering the offices, housing and parking around the building. This is context for
reading a venue, never evidence about it. ZCTA is also an order of magnitude coarser than a
census tract, which is why `layerRegistry` carries `geometry: 'zcta'` as its own value rather
than calling it `tract`.

**The geography changes mid-series, and a naive join would not error — it would invent a
trend.** ACS 5-year vintages through 2020 are tabulated on 2010-Census ZCTAs and 2021 onward
on 2020-Census ZCTAs. The codes are *reused* for redrawn polygons, so joining once and
applying to all fourteen years is correct for one half of the series and silently wrong for
the other. Measured from the downloads themselves: every file through `ACSDT5Y2020` has
33,120 ZCTA rows, every file from `ACSDT5Y2021` has 33,774. Each venue is therefore resolved
in **both** vintages and `load.py` picks per year; the venue panel prints which boundary set
the number it is showing was published on.

**Income is nominal.** The 2011 figure is in 2011 dollars and the 2024 figure in 2024
dollars. Nothing deflates it, so the series is not a real-terms trend — and the note saying
so ships inside the JSON, so it cannot be separated from the numbers it qualifies.

Three findings changed decisions before effort was spent on them:

- **Census tracts were the original plan and are not reachable here.** `data.census.gov` has
  no nationwide tract selector; a tract-level pull is ~3,600 API calls. The ACS *data* API
  also now requires a key — an unkeyed `api.census.gov` request 302s to `missing_key.html`.
  ZCTA files were already on disk, so ZCTA it is, with the coarseness stated rather than
  hidden.
- **The Census geocoder spells its own layer two ways.** The 2010 response keys it `ZIP Code
  Tabulation Areas`, the 2020 response `Zip Code Tabulation Areas`. A literal lookup made
  every 2020 result an empty list — which is *indistinguishable from "this point is in no
  ZCTA"*, so the first smoke test cheerfully reported all 19 venues as `2010_only` and
  nothing raised. The key is matched case-insensitively now, and an unexpected layer raises
  instead of returning an empty answer.
- **`in_scope` was the wrong venue filter.** It is a flag about the tenure hunt, not about
  being mapped: 3,980 venues carry it but 6,884 are on the map. Keying on it would have left
  2,904 visible dots with no context and no record saying why. The filter is "has a
  coordinate", which was measured to match the `venues.geojson` id set exactly.

**The gate found a real bias bug, and only because it was sabotage-tested.** All 29 checks
passed on the first run. Breaking the parser to let suppression sentinels through was **not
detected** — because these downloads encode suppression as `-`, never as `-666666666`, so
"no income is negative" is a check that cannot fail. Chasing why it could not fail turned up
the actual bug: ACS *censors* the extremes, publishing any ZCTA median at or above $250,000
as `250,000+` and at or below $2,500 as `2,500-`. A bare `float()` dropped both to null,
which quietly deleted the richest neighbourhoods from every average — and the censoring is
not random, so that is a bias, not noise. Three meanings, three different right answers:

| Cell | Means | Parsed as |
|---|---|---|
| `-` | suppressed, too few households to publish | `None` |
| `250,000+` | top-coded; the median is *at least* $250,000 | `250000` |
| `2,500-` | bottom-coded; the median is *at most* $2,500 | `2500` |

The invariant now re-reads the raw file cell by cell and asserts each case, and fails if it
ever finds fewer than 100 coded cells — a check that has gone quiet is not a check.
Re-sabotaged three ways afterwards (bare `float()`, nulls zeroed, bounds cleared): all three
detected, control clean.

**Unused downloads were turned into a test.** Subject tables S0801 and S1903 duplicate
universes already in B08006 and B19013. Reading both would give two columns that must agree
and no way to notice when they do not, so the gate asserts the agreement instead. A future
re-download that misaligns a column fails here rather than showing a slightly wrong
percentage on a venue panel.

**The browser payload is 3.9 MB, down from 12.7 MB.** Each venue-year is a positional array
decoded against the file's own `series_columns` list; four named keys per row across 96,376
rows was 12.7 MB of repeated field names shipped next to a 4.4 MB spine.

Verified in the browser at the Walter E. Washington Convention Center (ZCTA 20001): 2015
shows $85,976 / 35% transit / 2010 boundaries, 2024 shows $138,059 / 16% / **2020**
boundaries — the vintage switch happening where it should. The slider runs 1950–2026 and ACS
runs 2011–2024, so a year with no estimate falls back to the nearest published one and says
which year that is; a venue with no ZCTA at all gets the reason instead of a blank.

## ACS context areas (the choropleth)

```bash
.venv/bin/python -m pipeline.acs.shapes         # national boundary files -> acs_zcta_{2010,2020}.geojson
.venv/bin/python -m pipeline.acs.check_shapes   # 8 checks, incl. venue-in-its-own-polygon
cp pipeline/output/acs_zcta_20*.geojson console/public/data/
```

Boundaries for the **4,087 ZCTAs that contain a venue** — 12% of the country's ~33,000 —
shaded by one of four ACS measures, chosen from a dropdown. 3,885 polygons in the 2010
vintage and 3,927 in the 2020 vintage, 11.0 MB and 10.8 MB, one file per ZCTA definition.
Switching measure re-bins geometry already in memory; it never refetches.

**Blank on the map means "no venue here", not "not measured".** That claim is only honest
because the blank is uniform: a national choropleth with holes in it would read as a coverage
failure. A ZCTA that *is* drawn but has no published income that year gets its own flat color,
distinct from the ramp, so "no estimate" cannot be mistaken for "lowest bin".

**Two of the four measures are ranked within the year and two are on a scale fixed across all
years, and which is which was decided by measuring the data, not by taste.** Applying one rule
to all four would have put a false trend on screen in one direction or the other:

| Measure | Scale | Measured reason |
|---|---|---|
| Median household income | rank within year | p20 ran $35,361 (2011) → $54,905 (2024). Nominal dollars, nothing deflates them, so most of that climb is inflation. |
| Commute by transit | fixed, all years pooled | Median fell 1.45% → 0.83%, p80 6.8% → 4.0%. Real, comparable, and the largest movement in the data. |
| Commute 45 min or more | fixed, all years pooled | A ratio; comparable between years for the same reason. |
| Workers living here | fixed, all years pooled | A count with no deflation problem. |

Income *needs* ranking: a fixed dollar ramp would warm the whole map as the slider advances
and a reader would see neighbourhoods getting richer. Transit share needs the opposite, and
ranking it would have been the worse error — with per-year quintiles every bin holds a fifth
of the ZCTAs by construction, in every year, forever, so **the transit collapse would have
been rendered perfectly invisible.** Verified in the browser with the measure held on transit
and only the slider moved: cutoffs stayed identical (`0.0–0.1% / 0.1–0.7% / 0.7–2.0% /
2.0–5.9% / 5.9%+`) while the counts moved 660 → 1,008 in the bottom bin and 859 → 543 in the
top. Under a rank scale both years would have read as five flat bins of ~770.

The legend prints the cutoffs either way, and says which regime is in force: *"Fifths of the
venue neighbourhoods drawn in 2015"* versus *"Fifths of every year pooled. The counts are
2024."* For income the cutoffs visibly move — top bin `$72k+` in 2015, `$107k+` in 2024 —
which is the nominal-dollar problem disclosed rather than hidden.

Pooled cutoffs are computed across both ZCTA vintages as well as all years. Cutoffs that
depended on which boundary file happened to be loaded would shift when the slider crossed
2020, which is exactly the silent movement a fixed scale exists to rule out.

**Hover shows one figure, clicking shows all four — and the difference matters.** The map can
only shade one measure at a time, so a shaded area is answering one question out of four. The
panel lists all four for that ZCTA, marks which one the color was about, and names the venues
inside it, because the venue list is the most direct way to say the thing the color cannot:
this shape is drawn *because* those buildings are in it, and its numbers describe the postal
area around them rather than the buildings.

ZCTA 90089 is the case that justifies the panel. USC's campus has **no published income
estimate in 2015 but does have the other three** — 8.0% transit, 0.0% long commute, 628
workers — so it shades flat "no estimate" and the tooltip says exactly that, while three real
figures sit behind it that only the panel can reach. It also holds nine venues, which is the
many-venues-per-ZCTA relationship made visible rather than asserted.

Verified with synthesized mouse events over the real canvas, not by reading the code: tooltip
text, outline filter and cursor all track the polygon under the pointer; the outline survives
the mouse leaving (it falls back to the selection, so closing a panel is what clears it, not
moving the mouse); clicking a venue dot opens the venue panel and *not* the ZCTA panel,
because both layers receive the same click and the ZCTA handler checks `queryRenderedFeatures`
against the spine before firing; and switching the layer off removes all three ACS layers
rather than hiding them.

`zctaDetail` decodes the positional ACS rows independently of `contextForVenue`, which means a
column-order mistake would silently swap transit and commute rather than erroring. Cross-
checked across four ZCTAs in both vintages — all four measures agree exactly, and ZCTA 20001
reproduces the $138,059 recorded independently above.

**The vintage switches with the slider**, matching `load.py`: 2010-Census boundaries through
2020, 2020-Census boundaries from 2021. Only the file covering the current year is fetched,
and the old one is removed from the map rather than hidden, because ~11 MB of geometry costs
the same parked on the GPU as it does on screen. Verified: bins sum to exactly 3,885 at 2015
and exactly 3,927 at 2024.

**Simplification tolerance was chosen by measurement.** The gate re-tests every venue against
the polygon it was assigned, so "how much can these shapes be simplified" has a number rather
than an opinion:

| Tolerance | Venues outside their own ZCTA | Size |
|---|---|---|
| 0.0 | 50 | 30.5 MB |
| 0.0002 | 51 | 27.1 MB |
| **0.0005** | **55** | **21.8 MB** ← shipped |
| 0.001 | 101 | 15.4 MB |

The 50 at zero tolerance are an irreducible floor: the Census API tabulation geography that
`geocode.py` queried and the 1:500,000 cartographic generalization genuinely disagree. Median
miss 13 m, worst 1.36 km, and **every offender is a venue on water** — marinas, a yacht club,
an underwater park, a dive site — whose coordinate sits offshore of a boundary that follows
the shoreline. Distance is what tells an artifact from an error; a genuinely wrong ZCTA would
be miles out, so the gate budgets 60 misses and caps any single one at 2 km. Coordinate
precision 4 instead of 5 was rejected: it saved 1.9 MB and cost three more misses.

**Shapefile outer rings wind clockwise, which is *negative* shoelace area** — the opposite of
the maths convention, and the opposite of RFC 7946, which wants counter-clockwise outer rings.
Writing the test the intuitive way (`> 0` is outer) made every hole a separate polygon and put
**1,427 venues outside their own ZCTA**. That is the number that justifies the budget being 60
rather than 0: a check set to "must be zero" would have been unattainable and switched off,
and this regression would have shipped. All 8 checks were sabotage-tested; reverting this one
line produced 988 failures on a single vintage.

## Outputs

| File | What it is |
|---|---|
| `output/venues.geojson` | Map payload (no `match_keys` — that would double the download) |
| `output/venues_full.json` | Full records **including `match_keys`** — the extraction lookup table |
| `output/venues.csv` | Human review in a spreadsheet |
| `output/spine_ambiguous_names.json` | Names owned by more than one venue |
| `output/spine_spotcheck_mlb.json` | Coverage gate result |
| `output/spine_settlements_rejected.json` | Cities the census mistook for venues |
| `output/spine_overpass_convention_rejected.json` | Rejected OSM hits, kept for review |
| `output/gold_tenure.json` | Kiki's rows + derived `venue_id` / `operator_normalized` |
| `output/gold_eval.json` | Recall of the gold rows — the step 4 proof |
| `output/gold_seed.csv` | Paste-ready template for seeding more gold rows |
| `output/ingest_manifest_<label>.json` | Every file copied, duplicated or skipped, with hashes |
| `output/articles.json` | Parsed articles — the input to extraction |
| `output/contract_events.json` | Extracted events — the input to span pairing |
| `output/extract_rejected.json` | Events the model returned that failed `validate_event`, with reasons — kept so a gap is never silent |
| `output/extract_run.json` | Per-article record of the extraction: candidates, repairs, tokens, latency |
| `output/tenure_records.json` | **The deliverable** — one row per operator's run at one venue |
| `output/tenure_records.geojson` | Map layer, with `render_end_year` driving the time slider |
| `output/tenure_records.csv` | Same rows in Kiki's column order |
| `output/contract_events.{geojson,csv}` | The intermediate layer — audit a span back to a sentence |
| `output/search_log.csv` | Searches performed, including the ones that found nothing |
| `output/review_queue.csv` | Everything the pipeline refused to decide, with article snippets |
| `output/federal_venue_awards.geojson` | The 8 federal awards that name a spine venue — the map layer |
| `output/federal_operator_profile.json` | $5.0B by operator, agency and fiscal year — deliberately not a map layer |
| `output/federal_exclusions.csv` | The 9,279 rows ruled out of scope, each with its `scope_reason` |
| `output/venue_zcta.json` | Each venue's 2010 and 2020 ZCTA + `zcta_match` — the resumable geocode cache |
| `output/acs_venue_context.json` | Browser payload, venue → year, positional arrays (3.9 MB) |
| `output/acs_venue_context.csv` | The same 96,376 venue-years unrounded and flat, for checking by hand |
| `output/acs_zcta_2010.geojson` | 3,885 venue ZCTAs on 2010-Census boundaries — the choropleth through 2020 (11.0 MB) |
| `output/acs_zcta_2020.geojson` | 3,927 venue ZCTAs on 2020-Census boundaries — the choropleth from 2021 (10.8 MB) |
| `raw/whd/whd_cases.json` | The 840-row WHISARD response, checked in so the numbers are reproducible without the mirror |
| `raw/whd/manifest.json` | The query, row count, fetch time and SHA-256 behind that snapshot |
| `output/labor_whd_profile.json` | Wage & hour by operator — no geography, and it says why |
| `output/labor_whd_cases.csv` | All 840 candidates with the `scope` each was judged into, rejections included |
| `fixtures/usb/` | Checked-in fake USB stick — the corpus behind the ingest numbers and the dress rehearsal |
| `_rehearsal/output/` | Where the dress rehearsal writes. Disposable, rebuilt every run, never read by anything |

## Design notes

- **`venue_id` is `wd-<QID>`, never the name.** Names change when sponsors change; a
  foreign key that moves with a naming-rights deal is not a foreign key.
- **`aliases` carry date ranges.** This is what lets a 2001 article saying "Enron Field"
  and a 2015 article saying "Minute Maid Park" resolve to the same venue.
- **Name history is thin, and the panel says so rather than hiding.** Only **78 of 6,884**
  venues have any dated name; a live sample of 250 venues found dated `P1448` on 2.8% and
  *nothing at all* beyond the canonical name on 69.2%. The venue panel's "Name history"
  heading is therefore always rendered: an empty section that disappeared made "no source
  dates these names" read identically to "this venue never changed name", and only the first
  is true. Hard Rock Stadium is the worked example — Q864339 has no `P1448`/`P1449`/`P2561`
  and no altLabels, so "Joe Robbie Stadium" appears in neither Wikidata nor OSM. Its `P138`
  (*named after*) does carry Joe Robbie with dates 1987-08-16→1996-08-25, but that property
  names **honourees, not venues**; deriving a stadium name from it would put a string on
  screen that no source states. Dated name history for the other ~98% needs a new dated
  source, not more inference.
- **Packed aliases are split for display behind a much stricter guard than the match-key
  one.** 137 aliases in the spine contain a comma and only **8** are packed lists; the rest
  are "Name, Place" disambiguations (`Memorial Stadium, Baltimore`), honorifics (`John A.
  Alario, Senior, Event Center`) or names that simply have a comma (`Pennsylvania Literary,
  Scientific, and Military Academy`). The pipeline's `split_packed_alias` can afford to be
  loose because it only produces *match keys*, which `usable_key` then filters — but a
  display name is read as a claim. Measured, the loose rule fires on 113 of the 137 and would
  print "Baltimore", "Texas" and "Scientific" as former venue names. `splitPackedName` in
  `spineTransform.ts` requires every part to be 2–6 words, ≥6 characters and to contain a
  venue word, and skips parenthesised strings outright (`Wells Fargo Arena (Dothan,
  Alabama)`). It splits exactly the 8 real lists and leaves the other 129 whole — verified in
  the browser against the shipped `venues.geojson`, not just in a unit test. The venue-word
  list deliberately omits `University`, `Recreation`, `Golf` and `Casino`, each of which was
  measured causing a bad split.
- **`in_scope`** marks stadium/arena/ballpark/convention/racetrack, or anything seating
  5,000+. Out-of-scope venues (ski resorts, campus gyms) are flagged, not deleted —
  deleting them would quietly shrink the denominator.
- **Gray dots are the point.** Every venue renders gray because no tenure data exists yet.
  Each one is a documented gap rather than an absence of history. That makes this one color
  the most-drawn thing in the console and the one checked hardest: at `#64748b` it measures
  4.55:1 on positron's land and 3.37:1 on its water — a coastal stadium sits on the boundary,
  so passing on land alone is not passing — and it clears 3:1 on all five composited ACS bins.
  A map where every dot is a gap must not be the map that looks empty.
- **The year slider says what it cannot do.** 4,177 of 6,884 venues (**60.7%**) have no
  `opened_date`, and the filter treats an unknown opening as "already open" — treating it as
  closed would delete more of the spine than it kept. That made the readout false at every
  position: dragging to 1850 drew 4,191 dots and labelled them "4,191 venues operating",
  when 4,177 of them were there only because the date is missing. The label is now "N venues
  drawn in *year*", with a line underneath giving the undated count and share (90% at 1927,
  63% at 2015) and stating that moving the slider will not remove them. The dates are the
  fix; until then the control describes itself.
- **The console filters by state; `city` was corrupt and is now fixed.** The corruption was
  invisible to a string check: 2,480 mapped venues (36.0%) held their own state's full name in
  `city` — Cajundome's was "Louisiana", Charlotte Motor Speedway's "North Carolina" — and where
  a state's name is also a real city it passed every validation. 177 venues were labelled city
  "New York" and **122 of them (69%) sat more than 60 km from Manhattan**, six of those around
  Niagara Falls at ~495 km. A city dropdown built on that would have filed Niagara Falls Country
  Club under New York City and looked authoritative doing it. It is now reverse-geocoded from
  each venue's coordinate (see *`city` came from the wrong rung of a chain* above), which is why
  the venue panel can show "New London, CT" where it used to show "Connecticut, CT". The filter
  itself still runs on `state`, which needs no repair: 5,799 of 6,884 carry one (84.2%), every
  value is a valid two-letter code, and there are 51 of them.
- **The 1,085 venues with no state are named, not hidden.** Filtering to a state drops them,
  so the sidebar says how many and why. Silently shrinking the denominator is the failure
  mode this whole project is arranged against.
- **Sidebar counts all describe the same set.** The type checkboxes count venues passing the
  *year and state* filters — not the whole spine — because picking Wyoming used to leave
  "18 of 6,884" sitting directly above "Other 2,105". Their order still comes from the
  whole-spine ranking, so eleven checkboxes do not rearrange under the cursor every time the
  slider moves, and types that fall to zero stay listed: "Ballparks 0" is an answer.
- **The console is light, and every color in it was computed rather than chosen.** It was a
  dark navy dashboard. The reason for changing is not taste: this is a thing Kiki hands to
  someone, and a dark dashboard reads as a monitoring tool for a *system* while a light one
  reads as a document about a *subject*. It also screenshots and prints without inverting.
  The forcing issue was measured, though — the dark palette shipped two greys that failed AA
  (`#64748b` at 3.96:1, `#475569` at 2.48:1 against `#0b1120`), and `#64748b` was the color of
  "no operator on record", "this is a documented gap" and the ACS scope note. **The least
  readable text in the console was its most important text.** All of it is 11–13px, so the 3:1
  large-text exemption applies to none of it. `console/src/theme.ts` now holds every token with
  its measured ratio; the minimum anywhere is 5.17:1 against AA's 4.5, and control outlines get
  a separate token because WCAG 1.4.11 governs them at 3:1 rather than 4.5:1.
- **The choropleth ramp is tuned against the composited fill, not the hex.** The ACS layer draws
  at `fill-opacity: 0.55`, so what a reader sees is each bin blended over positron's `#fafaf8`
  land — much lighter than the value in the source. Measuring the raw hex instead produced a
  confident, wrong "3.10:1 worst case" in a code comment, and under it the darkest bin actually
  left the venue dots at **2.62:1**, failing 1.4.11 on exactly the neighbourhoods where the data
  is densest. Lifting the dark end from `#6b96c4` to `#88add2` puts the worst case at 3.00:1.
  It cost the ramp real range — composited end-to-end fell from 1.67:1 to 1.49:1 — and that is
  the right trade only because the legend carries the exact cutoffs, so the shading has to show
  direction while a dot that fails is information some readers simply do not get. The white halo
  around each dot is a separator, not the guarantee; it measures 1.05–1.13:1 against land and
  the bins and is documented as such rather than credited with work it does not do.
- **The `planned` layer rows have no opacity dimming** (0.42 → ~2.3:1): twelve of seventeen
  layers are unbuilt and saying so is the point, so status is carried by dot color and badge.
- **Google Places is not used.** Its license forbids storing results and rendering them on
  a non-Google map.
- **MapLibre + CARTO, not Mapbox** (the plan says Mapbox). Mapbox GL requires an account
  with a card on file even on the free tier. MapLibre is the open-source fork — same
  expression syntax, same `setFilter`/`addLayer` API — and CARTO's positron basemap serves
  vector tiles with no key. Swapping basemaps is one line (`STYLE_URL`), which is exactly how
  it moved from dark-matter to positron when the console went light.
  Note `optimizeDeps.exclude: ['maplibre-gl']` in `vite.config.ts`: without it Vite's
  dep optimizer breaks MapLibre's tile worker URL and the map renders blank *silently*.
- **A stale `node_modules/.vite` can kill the GeoJSON worker while leaving the basemap
  alive.** Seen here on a dev server that had been up for two days: CARTO's tiles, labels and
  attribution drew correctly while *every* GeoJSON source silently never tiled —
  `isSourceLoaded` false forever, `querySourceFeatures` returning 0, nothing logged. That
  partial failure is worse than a blank map, because a map that looks healthy sends you
  hunting through your own data instead; it cost a long detour through the spine's
  coordinates. What settled it was adding a throwaway one-point GeoJSON source, which failed
  too — that rules out the data and leaves the worker. The fix is `rm -rf node_modules/.vite`
  and a server restart. One thing *not* to chase: the `?v=<hash>` suffix on the maplibre
  module URLs is present in the working state as well, so it is not the tell. The mechanism
  behind this is still unconfirmed, and it is recorded here as a symptom and a remedy rather
  than as an explanation.
- **The dev server watches files and drops the module graph, because `hmr: false` otherwise
  serves pre-edit code forever.** Vite invalidates its module graph as part of the HMR path,
  so with HMR off `transformRequest` keeps returning the transform it made the first time —
  while the `no-store` header makes every fetch look fresh. This is worse than having no
  reloading at all: an edit appears to have been made *and verified* when what was tested was
  the code from before it. It cost a debugging session here — the browser was throwing
  `Cannot read properties of undefined` from a three-argument call to a function that had
  taken four arguments on disk for ten minutes. `server.ts` now calls
  `moduleGraph.invalidateAll()` on any source change, tested both ways: a probe comment
  appeared in the served module within two seconds and disappeared again on revert.

## Console verification pass (2026-08-11)

The console was walked end to end in a browser at 1280×800 — every section, the slider across
its whole range, the state filter crossed with the choropleth and the type filters, a venue
panel on a venue that has both federal awards and ACS context, search, and all four panels.
Four defects. The first three are the same kind: **a sentence that states a number is a claim
about the data, and a hand-written one keeps reading true after the data moves.** The fourth
was found by accident and was the worst of them.

**1. The choropleth went silent outside ACS coverage.** ACS runs 2011–2024; the slider runs
1850–2026, so most of the slider is outside it. At 1990 `choroplethFor` returned no bins, and
two things happened at once: the sidebar's legend block was gated on `bins.length > 0` and
disappeared entirely — including the "No estimate in *year*" row that exists to explain the
tan — while `matchColors` returns its bare fallback on an empty color map, so every polygon
in the vintage on screen (3,885 on 2010 boundaries, 3,927 on 2020) was painted
`NO_VALUE_COLOR`. The result was a uniform tan wash over the whole
country with no legend, no note and no error. That silence reads as "this neighbourhood
measured low", which is the one thing the no-estimate color exists to prevent. The
`Choropleth` now carries the published `years` and the sidebar renders the uncovered case
explicitly, naming the span from the payload rather than from prose. Checked at 1850, 1990,
2010, 2025 and 2026 against 2011, 2018 and 2024, on all four measures: the note and the bins
appear in exactly one state each, never both and never neither.

**2. `VenuePanel` typed the ACS span by hand.** "ACS 5-year estimates run 2011–2024" was
prose asserting the shape of the payload. It now reads `acsYears` and prints the same
sentence from the data.

**3. The federal panel typed its whole rejection ratio, and one figure was already wrong.**
"9,672 awards were read and 393 kept … 8,909 rows on its own, which would make Sodexo look
roughly **400×** the size of Aramark." The first two figures are still right. The third is
not reproducible from the current export by any reading — folding the remote-site rows into
Sodexo gives 160× by dollars and 763× by award count — and nothing on screen, in the gates or
in the types had noticed. `operator_profile` was dropping every rejection count on the floor
and shipping only the survivors, which is why the panel had to retype them; it now carries
`rows_loaded` and `scope_counts` the way the labor profile already carried its own, and the
sentence is derived (9,672 read, 393 kept, 8,909 remote-site rows = 92% of the export and 23×
the in-scope set).

**4. A browser without WebGL2 got a blank white page, not a broken map.** Found by accident
while testing something else. `MapView` constructs `maplibregl.Map` inside an effect, and
React propagates a throw from an effect exactly as it propagates one from render — with no
boundary above it, the whole tree unmounts. Measured with WebGL denied:
`document.body.innerText.length === 0`, and React's own console warning saying to consider
adding an error boundary. No map, no sidebar, no message. That is the worst outcome this
console can produce, because the sidebar is where the evidence is — the venue counts, the
rejection ratios, the wage-and-hour figures and every caveat on them — and none of it needs a
GPU. A `MapErrorBoundary` now wraps the map alone, so a map failure costs the map.

Two details worth keeping. MapLibre **masks its own cause**: it does raise "WebGL2 is
required", but only after the constructor has half-built the map, and unwinding that
half-built object raises a *second* error — `Cannot read properties of undefined (reading
'destroy')` — which is the one the boundary actually receives. The first version of the
fallback therefore reported the wrong reason. `MapView` now checks for a `webgl2` context
before it constructs anything, so the accurate message is the one that propagates and there is
nothing half-built to unwind. And the fallback **names the cause** rather than apologising, on
the same principle as the rest of the console: hardware acceleration off, a remote desktop, or
a locked-down profile — and it says in as many words that the sidebar still works. Verified
both ways: with WebGL denied the fallback renders and the sidebar keeps its figures
(`sidebarAlive: true`, federal and labor totals present); with WebGL restored the boundary
does not appear and the map canvas mounts.

What came back clean, and is recorded so it is not re-walked without reason:

- **The slider**, at 45 stops across 1850–2026: header year, duplicate header year, sidebar
  year and handle position agreed at every stop; header count equalled sidebar visible count;
  the total stayed 6,884; counts rose monotonically 4,191 → 6,527; and the undated disclosure
  was right at every position (100% at 1850, 63% at 2026).
- **The state filter**, crossed with the choropleth: NY 374, CA 442, WY 18, TX 457, all
  6,527 — header, sidebar, dropdown label and the sum of checked type rows all agreed. Unticked
  type rows correctly keep their pre-filter count rather than reading zero.
- **The venue panel** on Walter E. Washington Convention Center at 2018: three Centerplate
  awards with PIIDs, the match rule stated, ACS context, ZCTA 20001 on 2010 boundaries, and the
  name-history gap stated rather than hidden.
- **Search**: misses are labelled and say that old names were searched too; ambiguous names are
  disambiguated by city and date span; alias hits say which alias matched; a venue outside the
  slider year is flagged as not built yet. `joe robbie` returns nothing, which is the known
  source gap above and not a search bug.
- **The labor panel** reconciles exactly against `labor_whd_profile.json` — every part sums to
  its stated total (231 cases, $2,146,787, 2,459 workers, $78,661, 39 repeat-violator cases,
  493 of 840 rejected = 59%).
- **The ZCTA panel** at 20001/2015 matches the payload row exactly (26k workers, $86k, 35%,
  17%), and the legend's bins plus its no-estimate count sum to the polygons drawn
  (3,754 + 131 = 3,885).

One note about the harness rather than the app: **Chrome throttles background tabs**, capping
`setTimeout` to about once a minute after five minutes and not firing `requestAnimationFrame`
at all. That, not the console, caused the 30-second timeouts and the apparently blank map that
were nearly written up as performance defects here. Measured through a `MutationObserver`,
which is a microtask and is not throttled, a single slider step is **81 ms** and a 45-stop
sweep is **5.1 s**.

All gates green after the fixes: federal 27, labor 66, ACS 29, shapes 8, spans, end-to-end.

## Considered and rejected: AlphaEarth Foundations

Evaluated 2026-08-13 and not used. Recording it here because "we never thought of it" and "we
thought about it and it does not fit" look identical from outside.

Google DeepMind's [AlphaEarth Foundations](https://arxiv.org/abs/2507.22291) (July 2025) is a
64-dimensional learned embedding per 10 m pixel per year, 2017–2025, global, published in the
Earth Engine catalog as `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` and mirrored as Cloud Optimized
GeoTIFFs at `gs://alphaearth_foundations`.

**It is not rejected on licensing.** The dataset is CC-BY 4.0, which clears this project's
redistribution constraint — a rarer thing than it sounds, and the reason it was worth checking
at all. The Earth Engine *platform* terms restrict the free tier to non-commercial use, but the
GCS route is bound only by CC-BY.

It is rejected on relevance. AlphaEarth encodes what the land surface physically looks like
from orbit. This project asks who holds a food service contract and what happens to the people
working under it. There is no physical channel connecting the two:

- Aramark and Sodexo running the same concourse produce identical reflectance, backscatter and
  canopy height. A contract changing hands is invisible from space.
- At 10 m a stadium is roughly 20×20 pixels. The embedding can separate "large impervious
  structure with parking" from "row crops", which the venue spine already asserts with a
  source.
- Nothing in it can name an operator, a contract, a wage claim or a bid.

The one defensible use would be year-over-year change detection to corroborate *construction*
dates — a stadium being built or demolished is genuinely visible. That is narrow, and it would
have to be labelled as corroborating a capital project and inferring nothing about operators.

The cost is also not small. A 64-dimensional vector cannot be drawn, so using it would first
require inventing a derived product — PCA, clustering, a similarity scalar — and defending what
that product *means* to a reader. Full-depth embeddings run about 640 MB per km². That is days
of tile plumbing in exchange for no new verifiable fact about food service.

If the goal is more spatial richness, better-aligned candidates are OSM venue footprint
polygons, transit access, or moving ACS from ZCTA to tract.

## Next

Two things are waiting on people, not code:

1. **Kiki seeds 10–20 known Aramark accounts** in `SNZ_contract_tenure_table.xlsx`. Run
   `pipeline.spans.seed` with her venue names to get a paste-ready block with the
   coordinates and spelling already filled in, then `pipeline.spans.gold` to check them.
   Drop `verify` from the `source` cell once a row is confirmed — that is what promotes it
   from a note to a graded row.
2. **2–3 sample article files off the USB.** The ingest parsers are written and pass on
   synthetic Nexis and ProQuest exports, but those fixtures were written by the same author
   as the parser, which makes them a syntax check rather than a test. Same for the
   extraction prompt: it has never seen an article it did not effectively write itself.
   The first real file is likely to break something — that is what it is for.

The whole chain from an article to a colored dot is built and self-tested, and every test on
that chain is synthetic. Nothing more is learned by writing another fixture; the next real
information comes from the first article off the USB.

Meanwhile the three layers that *do* have real data behind them — federal awards, ACS context
and DOL wage & hour — are in the console with their limits stated on the panel rather than in
a footnote: that no wage & hour case is attached to a venue and why,
which boundary vintage each number came from, that ZCTA is a neighbourhood and not the
venue, that income is nominal, that a blank area on the choropleth is a place with no venue
rather than a place that was not measured, and that 8 of 393 federal awards touch this map
while the other 385 happen somewhere it does not reach.
