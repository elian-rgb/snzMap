# Adding data

How a new person gets articles or a spreadsheet onto the map.

Read this first: **there is no upload button, no Google Drive folder, and no web form.**
Everything below is a command run on a laptop that has the repo checked out. Adding data is
currently a developer task, not a contributor task. That is a real limitation and the last
section says what it would take to change it.

---

## Before anything

```bash
cd SNZMap
python3 -m venv .venv && .venv/bin/pip install requests openpyxl   # pipeline
cd console && bun install                                          # console
```

There is no `requirements.txt`. Add two more if you are ingesting articles rather than just
rebuilding the console:

```bash
.venv/bin/pip install striprtf pdfplumber    # .rtf and .pdf parsing
```

Both are imported lazily and raise a named error telling you to install them, so a missing
one fails with an explanation rather than a traceback. `.docx` needs nothing extra — it is
read as a zip.

Article extraction calls the Anthropic API and costs money. The key lives in `.env` at the
repo root (gitignored, never committed) and is **not** loaded automatically:

```bash
set -a; . ./.env; set +a
```

Skip that and the extractor stops on the first uncached article rather than running up a
bill against a key it does not have. Everything else in this document runs offline and free.

---

## Path A — adding news articles

This is the path the project was built for and the one that works end to end.

### 1. Where the files go

```
pipeline/articles/raw/<label>/<operator>/<whatever>.rtf
```

`<label>` is a batch name you choose (`usb1`, `usb2`, `sodexo-2026`). `<operator>` is the
company the export is about. Both become traceable metadata on every extracted event, so
`source_file` on a row in the console points at a file a person can actually open. An event
nobody can trace back to a document is not evidence.

Copy files in with the collector rather than by hand — it hashes every file, records where it
came from, and refuses to write to the source volume:

```bash
# Always dry-run first. It reports what it would copy and what it would skip.
.venv/bin/python -m pipeline.ingest.collect /Volumes/USB/articles --label usb2 --dry-run
.venv/bin/python -m pipeline.ingest.collect /Volumes/USB/articles --label usb2
```

This writes `pipeline/output/ingest_manifest_usb2.json` listing every file copied, every
duplicate detected by SHA-256, and every file skipped with the reason.

**Accepted formats:** `.txt` `.text` `.htm` `.html` `.rtf` `.pdf` `.docx`

**Not accepted:** anything else — spreadsheets, images, `.doc`. They are recorded in the
manifest as skipped rather than silently ignored.

**Scanned PDFs will not work.** A PDF that is page images with no text layer raises rather
than returning an empty string. 236 of the 602 articles in the current corpus are page scans
and were skipped for exactly this reason. Getting them in needs OCR, which this pipeline
does not do.

### 2. Parse the files into articles

```bash
.venv/bin/python -m pipeline.ingest.run --show 3
```

Produces `pipeline/output/articles.json`. One raw file usually contains *hundreds* of
articles concatenated together — the parser splits Nexis, ProQuest and ProQuest-RTF layouts.

**Check two numbers before going further.** They are printed at the end of the run:

| Number | What it means | What a bad value looks like |
|---|---|---|
| `text retained` | characters that landed inside some article ÷ characters in the file | Low means the splitter is throwing articles away |
| `body share` | characters in `body_text` ÷ characters in the file | Low means header parsing is eating the article body |

On the first real export `body share` came in at **2.7%** and everything downstream looked
fine — 4 files parsed to 4 articles with a median body of 28 characters. The pipeline was
"working" and producing almost nothing. It is now 79.2%. If your number is low, stop; the
extraction step will happily spend money on empty prompts.

### 3. Extract events

```bash
# Free. Builds every prompt, estimates tokens and cost, calls nothing.
.venv/bin/python -m pipeline.extract.run --dry-run

# A real trial on 5 articles before committing to the corpus.
.venv/bin/python -m pipeline.extract.run --limit 5

# The whole thing.
.venv/bin/python -m pipeline.extract.run
```

**Cost: about 3.5¢ per article.** The 366-article corpus cost $12.85 and took 29 minutes.

Re-running is nearly free. Every response is cached on disk by a hash of the request, so a
second run re-reads what it already paid for and spends only on genuinely new articles. An
interrupted run can simply be restarted. A finished run can be replayed with **no API key at
all**.

Read the summary block at the end. The line that matters most:

```
venue_id not offered   0
```

That is the drift indicator. The model is given a candidate list and may only choose from it;
anything above zero means it invented an ID that was repaired. Zero is what you want.

### 3b. Check whether the extraction is any good

```bash
.venv/bin/python -m pipeline.audit.sample --n 20      # draws a seeded random sample
# fill in the `verdict` column of pipeline/output/audit_sample.csv
.venv/bin/python -m pipeline.audit.score --auditor "your name"
```

Free, offline, and the only thing standing between "we extracted 178 events" and "we
extracted 178 events and here is how often they are right."

Each row carries the **article excerpt the claim came from**, so judging one is reading a
paragraph, not hunting through a 600-article `.rtf`. Allowed verdicts are printed by the
sample command; `cant_tell` is real and is excluded from the denominator rather than
counted either way.

Two things this deliberately does **not** do:

- **It does not sample from `review_queue.csv`.** That file holds records the pipeline
  already doubted; scoring only those would measure the pipeline's self-doubt and report a
  precision far below the truth. The sample is drawn uniformly from all events.
- **It does not measure recall.** Precision is "of what we produced, how much is true".
  Recall is "of what exists, how much did we find", and that needs rows written from
  outside the pipeline — `pipeline/spans/seed.py` and the workbook, still Kiki's job. The
  console reports the two separately because they fail for different reasons.

`--auditor` is recorded. An audit run by whoever built the extractor is weaker evidence
than an independent one, and `audit_summary.json` carries `independent: false` so the
console can say so out loud instead of letting a reader assume.

The current run: **20 sampled, 14 correct, 48–86% at 95% confidence.** The interval is
reported because at n=20 the bare "70%" is a wrong big number.

### 4. Pair, emit, publish

```bash
.venv/bin/python -m pipeline.spans.pair      # events -> operator runs
.venv/bin/python -m pipeline.emit.records    # runs -> geojson + csv
cp pipeline/output/*.geojson console/public/data/
cp pipeline/output/audit_summary.json console/public/data/   # the accuracy line
```

That last `cp` is the step people forget. Nothing appears on the map until the files are
copied into the console's public directory — the console reads from `console/public/data/`,
not from `pipeline/output/`.

### 5. Look at it

```bash
cd console && bun run dev
```

New venues appear as magenta rings under **From the articles** in the sidebar. Click a row to
fly to it.

---

## Path B — adding a CSV

**There is no generic CSV loader, and that is deliberate.**

Every source in this project has its own module, because every source joins to a venue by a
different key and needs different scope rules:

| Source | Module | How it finds the venue |
|---|---|---|
| Federal awards | `pipeline.federal.load` | venue name in the award description, **and** ZIP inside the venue's ZCTA, **and** the name is a recorded alias |
| Labor cases | `pipeline.labor.load` | operator name only — **never** venue |
| ACS | `pipeline.acs.load` | venue coordinates → ZCTA polygon |
| Articles | `pipeline.extract.*` | token matching against venue names and aliases |

The labor loader is the instructive one. WHD case records carry an employer address, so it is
technically possible to join them to venues by ZIP — and it refuses to. One ZIP in the data
contains 179 cases and 420 venues. A ZIP that holds both a case and a venue is a coincidence,
not evidence, and a map that drew that join would be inventing a fact.

**So adding a new CSV source means writing a module.** The shape is:

1. Create `pipeline/<source>/load.py`.
2. Read the CSV. Do not drop rows you cannot use — tag them.
3. Decide scope explicitly and record the decision per row (`in_scope`, `not_food_service`,
   `foreign_performance`, …). A row excluded for a stated reason can be argued with; a row
   that vanished cannot.
4. Join to the spine using `pipeline.extract.candidates.find_candidates` for name matching,
   or coordinates → ZCTA via `pipeline.acs.geocode`. **Require more than one gate.** Federal
   awards use three and still only 8 of 9,672 matched.
5. Write `pipeline/output/<source>.geojson` with a `venue_id` on every feature.
6. Add a `LayerDef` to `console/src/layerRegistry.ts` with `status: 'ready'` and
   `src: '/data/<source>.geojson'`.
7. Add a loader to `console/src/utils/<source>Transform.ts` following the existing ones.
8. `cp` the geojson into `console/public/data/`.

**Do not flip a layer to `ready` before the file exists.** The registry's `planned` status is
what lets the console tell a reader that 12 layers are missing. A layer marked ready with no
file behind it turns an honest gap into a broken one.

### The one CSV that already has a path

Ground-truth tenure rows for evaluating the extractor:

```bash
.venv/bin/python -m pipeline.spans.seed "Coors Field" "Madison Square Garden | 2005"
```

This resolves venue names against the spine and pre-fills the identity columns into
`pipeline/output/gold_seed.csv`. A human fills in operator and dates by hand from a source
they can cite. This is the only place in the project where hand-typed data is expected.

---

## Filling in the gold rows (the one job that is waiting on a person)

**`pipeline/output/gold_seed.csv` is already seeded with 24 venues.** Identity is filled —
exact spelling, city, state, coordinates. Seven columns are blank because they are the
actual knowledge being captured:

| Column | What to put |
|---|---|
| `operator` | the company, as you would say it — "Aramark", "Levy", "Delaware North" |
| `start_date` | `YYYY-MM-DD`, or `YYYY-01-01` if you only know the year |
| `start_precision` | `exact` / `month` / `year` / `approx` — say how sure the date is |
| `end_date`, `end_precision` | only if the run ended |
| `end_status` | `ongoing`, `ended`, or `unknown` — see below |
| `source` | **where you got it.** A URL, an article, a phone call |

Paste the filled rows under the header on the **`tenure_table`** tab of
`~/Downloads/SNZ_contract_tenure_table.xlsx`, then run:

```bash
.venv/bin/python -m pipeline.spans.gold        # loads and validates the workbook
.venv/bin/python -m pipeline.spans.evaluate    # scores the pipeline against it
```

### Four things that decide whether this measures anything

**1. Do not fill these in from the map, the console, or `tenure_records.csv`.** The gold set
is the ruler; reading it off the thing being measured makes the ruler agree with itself and
the resulting number is worthless. Use a source outside this project. If the only place you
can find a fact is this project's own output, leave the row blank.

**2. `end_status` is not a formality.** `ongoing` asserts they still hold it. `unknown`
admits you have not found the end. These are opposites and the map paints them differently —
an `ongoing` run is drawn to today, an `unknown` one stops where the evidence stops. The
seeder leaves it blank on purpose rather than defaulting it.

**3. Write `verify` in `source` if you are going from memory.** Rows whose `source` contains
that word are excluded from scoring rather than trusted. A remembered fact is a lead, not
ground truth, and this is how you record one without it silently becoming evidence.

**4. Fill in all 24, including the ones you expect the pipeline to miss.** The list mixes
venues the article corpus covers with venues it does not, deliberately. That mix is what
lets the gate separate *"the extractor failed"* from *"no article in the archive mentions
this place"* — reported as `misses` and `misses_no_coverage`. Skipping the ones you suspect
are gaps would delete exactly the rows that make the number interpretable.

### Why these 24 venues

Current MLB, NFL, NBA and NHL home venues that resolve in the spine. The frame is
**league membership, which is decided outside this project** — not "venues the pipeline
already found", which would have scored the pipeline against its own successes and reported
near-perfect recall while measuring nothing. Two of the 24 (U.S. Bank Stadium, Nissan
Stadium) do appear in the extraction output, by the rule rather than by selection.

These are also venues where a concessionaire is publicly documented, so the rows are
*fillable* — a gold set nobody can source is not a gold set.

Ten to twenty filled rows makes the gate live. Fewer, and `evaluate.py` prints its numbers
and explicitly refuses to call itself a gate.

---

## What someone else actually needs

To hand this to another person today, they need:

- the repo
- Python 3 and the virtualenv
- `bun` (for the console)
- an Anthropic API key, **only** if they are extracting new articles
- the article files themselves

They do **not** need Google Drive, a server, a database, or an account of any kind. The whole
thing runs on one laptop against files on disk.

## What it would take to make this a contributor task

Honestly: more than the current deadline allows. The pieces missing are

- a hosted place to put files, and a way to accept them that is not "plug in a USB"
- a generic CSV loader driven by a small mapping config (which column is the venue, which is
  the date, which is the operator) rather than a bespoke module per source
- a review step, because the join is the part that goes wrong — 147 of 178 extracted events
  name buildings this map is not a census of, and no automated join would have caught that

The middle one is the tractable piece and would be the right next thing to build. The first
and third are a different project.
