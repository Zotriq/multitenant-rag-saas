"""Split documents into overlapping chunks along paragraph and sentence boundaries."""

from __future__ import annotations

import re


def chunk_text(text: str, max_chars: int = 800, overlap: int = 120) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    pieces: list[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p)
        buf = ""
        for s in sentences:
            while len(s) > max_chars:  # a single enormous "sentence"
                pieces.append(s[:max_chars])
                s = s[max_chars - overlap:]
            if len(buf) + len(s) + 1 > max_chars and buf:
                pieces.append(buf)
                buf = buf[-overlap:] + " " + s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            pieces.append(buf)

    # Merge small neighbours so chunks carry enough context.
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(piece) + 2 <= max_chars:
            chunks[-1] = f"{chunks[-1]}\n\n{piece}"
        else:
            chunks.append(piece)
    return chunks
