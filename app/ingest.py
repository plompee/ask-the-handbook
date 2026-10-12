"""Turns uploaded files into (page, text) chunks small enough to cite precisely."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

TARGET = 900          # characters per chunk (a few paragraphs)
MAX_FILE = 15_000_000
KINDS = {".pdf": "pdf", ".txt": "text", ".md": "markdown"}


def kind_for(filename: str) -> str:
    ext = filename[filename.rfind("."):].lower() if "." in filename else ""
    if ext not in KINDS:
        raise ValueError("Only PDF, .txt and .md files are supported")
    return KINDS[ext]


def _split(text: str) -> list[str]:
    """Packs paragraphs (and, for very long ones, sentences) into chunks of about TARGET characters."""
    pieces = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"[ \t]+", " ", para).strip()
        if not para:
            continue
        if len(para) <= TARGET:
            pieces.append(para)
        else:
            pieces.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip())
    chunks, current = [], ""
    for p in pieces:
        if current and len(current) + len(p) + 2 > TARGET:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


def pdf_pages(data: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected")
        return [(page.extract_text() or "") for page in reader.pages]
    except PdfReadError as e:
        raise ValueError(f"Couldn't read this PDF ({e})") from e


def text_sections(raw: bytes, markdown: bool) -> list[str]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    if markdown:  # one "page" per top-level section, so citations point to a heading
        parts = re.split(r"(?m)^(?=#{1,2} )", text)
        return [p for p in parts if p.strip()]
    return [text]


def ingest(filename: str, data: bytes) -> tuple[str, int, list[tuple[int | None, str]]]:
    """Returns (kind, page_count, chunks). Raises ValueError with a readable message for unusable files."""
    if len(data) > MAX_FILE:
        raise ValueError("File is larger than 15 MB")
    kind = kind_for(filename)
    pages = pdf_pages(data) if kind == "pdf" else text_sections(data, kind == "markdown")
    chunks: list[tuple[int | None, str]] = []
    for n, page_text in enumerate(pages, start=1):
        heading = ""
        if kind == "markdown" and (m := re.match(r"#{1,2} (.+)", page_text.strip())):
            heading = m.group(1).strip()
            page_text = page_text.strip()[m.end():]
        for chunk in _split(page_text):
            # Start every chunk with its section heading ("Holidays:") so each one makes sense - and cites - on its own.
            chunks.append((n, f"{heading}:\n\n{chunk}" if heading else chunk))
    if not chunks:
        raise ValueError("No text found - is this a scanned PDF? Only PDFs with selectable text can be searched")
    return kind, len(pages), chunks
