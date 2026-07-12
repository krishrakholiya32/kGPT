"""
Text chunking for kGPT's RAG document knowledge base.

Deliberately not LangChain's RecursiveCharacterTextSplitter — a single
splitter function doesn't justify the dependency (kGPT dropped LangChain
project-wide, see llm.py). Same paragraph-aware-with-hard-cut-fallback
strategy, implemented directly.
"""

from typing import List

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks, preferring paragraph/sentence boundaries.

    Strategy: greedily pack paragraphs (split on blank lines) into chunks up to
    chunk_size. A single paragraph longer than chunk_size is hard-cut at
    sentence boundaries (". "), and a single sentence longer than chunk_size is
    hard-cut at the character limit as a last resort. Consecutive chunks
    overlap by `overlap` characters (taken from the end of the previous chunk)
    so a fact split across a chunk boundary isn't lost to retrieval entirely.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    # Expand any paragraph longer than chunk_size into sentence-level pieces.
    pieces: List[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            pieces.append(para)
            continue
        sentences = para.split(". ")
        buf = ""
        for i, sent in enumerate(sentences):
            piece = sent if i == len(sentences) - 1 else sent + ". "
            if len(piece) > chunk_size:
                # A single "sentence" is still too long — hard-cut it.
                if buf:
                    pieces.append(buf)
                    buf = ""
                for start in range(0, len(piece), chunk_size):
                    pieces.append(piece[start:start + chunk_size])
                continue
            if len(buf) + len(piece) > chunk_size:
                pieces.append(buf)
                buf = piece
            else:
                buf += piece
        if buf:
            pieces.append(buf)

    # Greedily pack pieces into chunks, carrying `overlap` chars forward.
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            carry = current[-overlap:] if overlap > 0 else ""
            current = f"{carry}\n\n{piece}" if carry else piece
        else:
            current = piece
    if current:
        chunks.append(current)

    return chunks
