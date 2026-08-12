"""One file in, plain text out. Format-specific work stops here.

Everything downstream — splitting concatenated exports, reading metadata headers, finding
the body — operates on text, so adding a format later means adding one function here and
nothing else.

Text is normalized to `\\n` line endings and NFC, and non-breaking spaces become real
spaces. Nexis in particular is full of U+00A0 between a month and a day, which turns
"March 3, 2005" into a string no date parser matches.
"""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

# Nexis and ProQuest .txt exports are usually Windows-1252, not UTF-8. Decoding cp1252 as
# latin-1 silently turns a smart quote into "â€™", which then lands in a headline and gets
# stored as the article's title. Try the strict decodes first and only fall back at the end.
ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

INVISIBLE = dict.fromkeys(map(ord, "\u00a0\u2007\u202f\u2060\ufeff\u200b\u200c\u200d"), " ")


class UnsupportedFormat(Exception):
    """The file is a kind we cannot read yet. Never swallowed — it lands in the report."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


class _Stripper(HTMLParser):
    """Tags out, text in reading order. Block tags become newlines so paragraph structure
    survives — a body collapsed onto one line is much harder for a human to check."""

    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "table", "section", "article", "blockquote"}
    DROP = {"script", "style", "head", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self._dropping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.DROP and self._dropping:
            self._dropping -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._dropping:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def from_html(raw: bytes) -> str:
    stripper = _Stripper()
    stripper.feed(decode(raw))
    stripper.close()
    return normalize(html.unescape(stripper.text()))


# `\binN` announces exactly N bytes of raw binary — ProQuest uses it to inline the page
# scans and the little document-link icon. The trailing space is a delimiter, not content.
_BIN = re.compile(rb"\\bin(\d+)[ ]?")


def strip_bin(raw: bytes) -> tuple[bytes, int]:
    """Drop `\\binN` payloads, returning the remaining RTF and the bytes removed.

    This is a correctness fix, not a size optimisation. Binary is not text and no RTF
    reader should be asked to guess: a PNG contains `{` and `}` bytes, and striprtf counts
    those as RTF group delimiters. Measured on the real Sodexo export, one 5.6 MB page scan
    carries 6,981 more closing braces than opening ones, so the group depth goes negative
    and striprtf concludes the document ended — mid-file, without raising anything. The
    observed cost was 99 of 100 articles in that export and 494 of 500 in the Aramark one,
    dropped in silence. Skipping each payload by its own declared length is exactly what
    the RTF spec says the length is for, and it recovers all 600.
    """
    out: list[bytes] = []
    i = dropped = 0
    while True:
        match = _BIN.search(raw, i)
        if match is None:
            out.append(raw[i:])
            return b"".join(out), dropped
        out.append(raw[i:match.start()])
        count = int(match.group(1))
        dropped += count
        i = min(match.end() + count, len(raw))


def from_rtf(raw: bytes) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError as exc:  # pragma: no cover - environment problem, not data
        raise UnsupportedFormat("striprtf is not installed (pip install striprtf)") from exc
    clean, _ = strip_bin(raw)
    return normalize(rtf_to_text(decode(clean), errors="ignore"))


def from_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("pdfplumber is not installed (pip install pdfplumber)") from exc

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    text = normalize("\n\n".join(pages))
    if not text.strip():
        # A scanned export has no text layer at all. Saying so beats handing the extractor
        # an empty body and calling the article "processed".
        raise UnsupportedFormat("PDF has no extractable text layer (scanned? needs OCR)")
    return text


def from_docx(path: Path) -> str:
    import zipfile

    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    return normalize(html.unescape(re.sub(r"<[^>]+>", "", xml)))


def to_text(path: Path) -> str:
    """Plain text for any supported article file. Raises `UnsupportedFormat` otherwise."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        return normalize(decode(path.read_bytes()))
    if suffix in {".htm", ".html"}:
        return from_html(path.read_bytes())
    if suffix == ".rtf":
        return from_rtf(path.read_bytes())
    if suffix == ".pdf":
        return from_pdf(path)
    if suffix == ".docx":
        return from_docx(path)
    raise UnsupportedFormat(f"no adapter for {suffix!r}")
