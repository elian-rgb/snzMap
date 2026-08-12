"""Plain text in, article records out.

A database export is not one article. A single Nexis .txt is routinely 25 articles nose to
tail, and if the splitter is wrong every downstream number is wrong in a way that looks
fine: bodies silently merge, one headline gets credited with another article's contract,
and the row count still looks plausible. So splitting is measured, not assumed — see
`coverage()`, which reports how much of the source text actually landed inside an article.

Two vendor layouts are recognized:

    Nexis classic       "3 of 25 DOCUMENTS", ALL-CAPS labels (HEADLINE:, BODY:)
    Nexis / ProQuest    "Document 3 of 25", Title-Case labels (Publication date:, Full text:)

Anything unrecognized becomes one article with whatever the header scan could find. It is
never dropped, and never invented: a field we could not read stays null and the reason is
recorded in `problems`. `source_publication`, `source_date`, `source_title` and
`source_file` are all required by the event schema, so an article missing any of them can
produce no valid events at all — which makes those counts the ingest gate, not a footnote.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from .formats import UnsupportedFormat, to_text

# A block shorter than this between two separators is export furniture — a page number, a
# copyright line, the "25 documents retrieved" banner — not an article.
MIN_BLOCK_CHARS = 200

# Where one article ends and the next begins. Both vendors number their documents, which is
# far more reliable than looking for a headline.
DOC_START = re.compile(
    r"^[ \t]*(?:\d+\s+of\s+\d+\s+DOCUMENTS?"      # Nexis classic
    r"|Document\s+\d+\s+of\s+\d+)[ \t]*$",        # ProQuest / Nexis Uni
    re.M | re.I,
)
DOC_END = re.compile(r"^[ \t]*End of Document[ \t]*$", re.M | re.I)

# ProQuest's RTF/PDF export is a third layout, and it numbers nothing: measured on the real
# exports off the USB, "Document N of M" appears zero times in 600 documents. What it does
# print exactly once per record is a link line directly beneath the headline, which is why
# `BODY_TAIL` below already knew the string. Anchoring on it recovers all 600; without it the
# whole export parses as a single article and `body_share` collapses to 2.7%.
PROQUEST_LINK = re.compile(r"^[ \t]*ProQuest document link[ \t]*$", re.M)

# The export's own section headings. They sit exactly where a bare centered headline sits, so
# without this the positional fallback picks one up and files a real article under it.
FURNITURE = re.compile(
    r"^[ \t]*(?:ProQuest document link|LINKS|DETAILS|ABSTRACT(?: \(ABSTRACT\))?"
    r"|Headnote)[ \t]*$")

# `LOAD-DATE`, `Publication date`, `Full text`. Values may continue onto indented lines.
LABEL = re.compile(r"^[ \t]*([A-Za-z][A-Za-z\-' ]{1,28}):[ \t]*(.*)$")

# A lone "Body" line (no colon) opens the text in the newer Nexis layout. ProQuest's RTF
# export uses a lone "FULL TEXT" for the same job — and because it is bare, the labelled
# header scan cannot see it. Measured before this was added: `body_at` stayed 0 on every one
# of the 600 real documents, so the body fell back to the whole block and was then cut to
# ~30 characters by `BODY_TAIL` below.
BARE_BODY = re.compile(r"^[ \t]*(?:Body|BODY|FULL TEXT|Full text)[ \t]*$", re.M)

# ProQuest separates documents with a rule of underscores.
RULE = re.compile(r"^[\W_]+$")

BODY_LABELS = ("body", "full text")
TITLE_LABELS = ("headline", "title", "document title")
PUB_LABELS = ("publication title", "publication", "source", "newspaper")
# `DATELINE` is deliberately absent: in Nexis it holds a place ("DENVER"), not a date, and
# reading it as one costs every classic-format article its publication date.
DATE_LABELS = ("publication date", "date", "publication info")

# The only labels trusted *after* the body starts. ProQuest prints its real citation block
# below the full text, so the scan cannot stop at the body — but nor can it treat every
# "Smith said: ..." line inside an article as a header field.
KNOWN_LABELS = set(BODY_LABELS + TITLE_LABELS + PUB_LABELS + DATE_LABELS) | {
    "author", "byline", "copyright", "load-date", "language", "section", "length",
    "publication-type", "subject", "company / organization",
}

# A header line this long is a paragraph that happens to sit above the body.
MAX_HEADER_LINE = 200

# Where the article stops and the export's own citation block starts. ProQuest repeats the
# citation *below* the full text, and left in place it lands in `body_text` and gets read as
# if the article said it.
# `DETAILS` is matched case-sensitively and only alone on its line: it is ProQuest's own
# heading for the citation block, and lower-casing it would let any paragraph opening with
# the word "Details" truncate a real article.
BODY_TAIL = re.compile(
    r"\n[ \t]*(?:End of Document|Load-Date:|Publication title:|Publication date:"
    r"|ProQuest document link|Copyright \(c\)|Document URL:|(?-i:DETAILS)[ \t]*(?:\n|$))",
    re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Each alternative carries its own suffix: "jan[a-z]*|feb[a-z]*|...". Written as
# "|".join(MONTHS) + "[a-z]*" the suffix binds to December alone, and every spelled-out
# month except an abbreviated one stops matching.
_MONTH_ALT = "|".join(m + "[a-z]*" for m in MONTHS)
DATE_PATTERNS = [
    # March 3, 2005  /  Mar. 3 2005
    re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I),
    # 3 March 2005  /  03 Mar 2005   (ProQuest "Publication info" uses this)
    re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I),
]
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# US order. Every publication in this corpus is American; a European export would need a
# flag, and would be visibly wrong (month 13) rather than quietly wrong, most of the time.
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
# "March 2005" with no day. Recognized only so it can be reported as incomplete — filling in
# the 1st would make up a publication date that no article carries.
MONTH_ONLY = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I)


def parse_date(raw: str | None) -> str | None:
    """`YYYY-MM-DD`, or None. Never guesses a missing day and never invents a year."""
    if not raw:
        return None
    for pattern in DATE_PATTERNS:
        m = pattern.search(raw)
        if not m:
            continue
        a, b, year = m.groups()
        month, day = (MONTHS[a[:3].lower()], int(b)) if a[0].isalpha() else (MONTHS[b[:3].lower()], int(a))
        try:
            return dt.date(int(year), month, day).isoformat()
        except ValueError:
            return None
    for pattern, order in ((ISO_DATE, "ymd"), (SLASH_DATE, "mdy")):
        m = pattern.search(raw)
        if m:
            g = [int(x) for x in m.groups()]
            year, month, day = (g[0], g[1], g[2]) if order == "ymd" else (g[2], g[0], g[1])
            try:
                return dt.date(year, month, day).isoformat()
            except ValueError:
                return None
    return None


def _proquest_link_bounds(text: str) -> list[int]:
    """Document starts for ProQuest's unnumbered RTF/PDF layout.

    The link line is the anchor, but the record does not start there — the headline and
    byline sit above it, and a split at the link would credit every headline to the previous
    article. Walking back to the blank line above is not enough either: a scanned page is
    filed with a headline but no byline, so the group is one line for some records and two
    for others. What is uniform is what sits above the group — the previous record's citation
    block, whose fields are all `|`-delimited. The first such line going up is the real edge.
    """
    lines = text.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    line_at = {off: i for i, off in enumerate(offsets)}

    bounds: list[int] = []
    for m in PROQUEST_LINK.finditer(text):
        i = line_at.get(m.start())
        if i is None:
            continue
        j = i - 1
        while j >= 0 and not lines[j].rstrip().endswith("|"):
            j -= 1
        bounds.append(offsets[j + 1])
    return sorted(set(bounds))


def split_documents(text: str) -> tuple[list[tuple[int, str]], int]:
    """`[(offset, block)]` plus the number of characters that fell outside every block.

    Offsets are into the original text and become part of `event_id`, so an event can be
    traced to a byte range in a file a person can open.
    """
    bounds: list[int] = []
    starts = [m.start() for m in DOC_START.finditer(text)]
    links = [] if starts else _proquest_link_bounds(text)
    if starts:
        bounds = starts
    elif links:
        bounds = links
    else:
        ends = [m.end() for m in DOC_END.finditer(text)]
        # A trailing terminator at the very end closes the last article; it opens nothing.
        bounds = [0] + [e for e in ends if e < len(text) - 1]

    if not bounds:
        return ([(0, text)] if text.strip() else []), 0

    blocks: list[tuple[int, str]] = []
    dropped = bounds[0]  # the export's own banner, before the first document
    edges = bounds + [len(text)]
    for start, end in zip(edges, edges[1:]):
        block = text[start:end]
        if len(block.strip()) < MIN_BLOCK_CHARS:
            dropped += len(block)
            continue
        blocks.append((start, block))
    return blocks, dropped


def read_labels(block: str) -> tuple[dict[str, str], int]:
    """Header labels for `block`, and the offset where the body begins.

    Values continue onto following lines until a blank line or the next label, because Nexis
    wraps long BYLINE and SECTION values and ProQuest wraps almost everything.
    """
    labels: dict[str, str] = {}
    lines = block.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    body_at = 0
    current: str | None = None
    for i, line in enumerate(lines):
        m = LABEL.match(line)
        if m:
            name = m.group(1).strip().lower()
            if body_at and name not in KNOWN_LABELS:
                current = None
                continue
            labels.setdefault(name, m.group(2).strip())
            current = name
            if name in BODY_LABELS and not body_at:
                # ProQuest puts the article on the same line as the label
                # ("Full text: Aramark Corp. will ..."), so the body starts at the value,
                # not at the next line.
                body_at = offsets[i] + m.start(2)
                current = None
            continue
        if not body_at and BARE_BODY.match(line):
            body_at = offsets[i] + len(line) + 1
            continue
        if current and line.strip() and line[:1] in " \t":
            labels[current] = (labels[current] + " " + line.strip()).strip()
        elif not line.strip():
            current = None

    return labels, body_at


def _plain_lines(block: str, until: int, count: int = 8) -> list[tuple[str, int]]:
    """Unlabelled header lines with their end offsets — the centered publication, date and
    headline that Nexis prints with no label at all."""
    out: list[tuple[str, int]] = []
    pos = 0
    for line in block.split("\n"):
        end = pos + len(line)
        pos = end + 1
        if until and end > until:
            break
        s = line.strip()
        if not s or len(s) > MAX_HEADER_LINE:
            continue
        # A headline is allowed to contain a colon. `LABEL` matches any short word followed
        # by one, so "Press Release: Manhattan Associates Reports..." was being read as a
        # header field named "press release" and dropped from the candidate headlines —
        # after which the fallback took the next plain line, which is export furniture.
        # Measured on the real exports: 19 articles, some with 30,000 characters of body,
        # were filed under the headline "ProQuest document link". A colon only means a
        # header when the name in front of it is one this parser actually knows.
        labelled = LABEL.match(s)
        if labelled and labelled.group(1).strip().lower() in KNOWN_LABELS:
            continue
        if RULE.match(s) or DOC_START.match(s) or FURNITURE.match(s) or BARE_BODY.match(s):
            continue
        out.append((s, end))
        if len(out) >= count:
            break
    return out


def parse_block(block: str, offset: int, source_file: str) -> dict[str, Any]:
    """One article record. Missing fields stay null and say why in `problems`."""
    labels, body_at = read_labels(block)
    problems: list[str] = []

    def pick(names: tuple[str, ...]) -> str | None:
        for n in names:
            if labels.get(n):
                return labels[n]
        return None

    title = pick(TITLE_LABELS)
    publication = pick(PUB_LABELS)
    date_raw = pick(DATE_LABELS)

    # The classic Nexis layout labels nothing above BODY: publication, date and edition are
    # bare centered lines. The date line is the anchor — what sits above it says which
    # layout this is. One line above (classic) is the publication; two (newer Nexis, and
    # loose clippings) are the headline then the publication.
    plain = _plain_lines(block, body_at)
    at_date = next((i for i, (s, _) in enumerate(plain) if parse_date(s)), None)
    consumed = -1
    if at_date is None:
        if plain and not title:
            title, consumed = plain[0][0], 0
    elif at_date == 1:
        publication = publication or plain[0][0]
        consumed = at_date
    elif at_date >= 2:
        title = title or plain[0][0]
        publication = publication or plain[1][0]
        consumed = at_date
    if at_date is not None and not date_raw:
        date_raw = plain[at_date][0]

    # A clipping with no BODY marker: everything below the header lines is the article.
    if not body_at and consumed >= 0:
        body_at = plain[consumed][1] + 1

    source_date = parse_date(date_raw)
    if not source_date:
        problems.append(
            f"no publication date (read {date_raw!r})" if date_raw
            else "no publication date found"
        )
        if date_raw and MONTH_ONLY.search(date_raw):
            problems.append("date has no day — not filled in")
    if not publication:
        problems.append("no publication name found")
    if not title:
        problems.append("no headline found")

    body = block[body_at:] if body_at else block
    body = BODY_TAIL.split(body)[0].strip()
    if not body:
        # An export that opened a full-text section and then closed it without a word is
        # telling us something specific, and it is not that the parser failed. In the real
        # ProQuest exports this is a page scan: the article exists only as an image, which
        # is why these records also carry a date-and-page line where a headline should be.
        # 236 of the 600 documents are this, and the signal is exact — every one of the 600
        # declared a full-text section, and exactly the empty ones supplied nothing. Saying
        # "empty body" for these would read as a bug in here and hide a third of the corpus
        # behind it, the same way `from_pdf` refuses to call a scanned page processed.
        problems.append(
            "citation only: export declared a full-text section and supplied none "
            "(page scan — text is in an image, needs OCR)"
            if body_at else "empty body"
        )

    return {
        "source_file": source_file,
        "source_offset": offset,
        "source_publication": publication,
        "source_date": source_date,
        "source_date_raw": date_raw,
        "source_title": title,
        "body_text": body,
        "problems": problems,
    }


def parse_text(text: str, source_file: str) -> tuple[list[dict[str, Any]], int]:
    blocks, dropped = split_documents(text)
    return [parse_block(b, off, source_file) for off, b in blocks], dropped


def parse_file(path: Path, source_file: str | None = None) -> dict[str, Any]:
    """Articles in one file. A format we cannot read is reported, not skipped."""
    rel = source_file or str(path)
    try:
        text = to_text(path)
    except UnsupportedFormat as exc:
        return {"source_file": rel, "articles": [], "chars": 0, "dropped_chars": 0,
                "error": str(exc)}
    except Exception as exc:
        # A truncated PDF or a .docx that is not really a zip must not end the run. One
        # corrupt file out of two thousand is a line in the report, not a stack trace that
        # loses the other 1,999.
        return {"source_file": rel, "articles": [], "chars": 0, "dropped_chars": 0,
                "error": f"{type(exc).__name__}: {exc}"}
    articles, dropped = parse_text(text, rel)
    return {"source_file": rel, "articles": articles, "chars": len(text),
            "dropped_chars": dropped, "error": None}


def coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of the source text survived splitting and body extraction.

    Low `text_retained` means the splitter is throwing articles away. Low `body_share` means
    header parsing is eating the article. Neither shows up in a row count.
    """
    chars = sum(r["chars"] for r in results)
    dropped = sum(r["dropped_chars"] for r in results)
    body = sum(len(a["body_text"]) for r in results for a in r["articles"])
    return {
        "source_chars": chars,
        "text_retained": round((chars - dropped) / chars, 4) if chars else 0.0,
        "body_share": round(body / chars, 4) if chars else 0.0,
    }
