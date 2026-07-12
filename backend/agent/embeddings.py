"""
Local embedding generation for kGPT's RAG document KB + cross-conversation memory.

Uses sentence-transformers (HuggingFace) — genuinely local inference, no API
calls, no added Gemini/Groq quota usage. Model choice (all-MiniLM-L6-v2,
384-dim) was verified directly on the Oracle ARM box before committing to it:
~539MB resident after load, ~14ms per query embed, ~7ms/chunk in batch — see
the kGPT project memory for the full benchmark.

uvicorn runs single-process in production (no --workers beyond the 2 set in
the systemd unit, each its own process with its own model instance — no
cross-process sharing needed since sentence-transformers' own load is cheap
enough per the benchmark). encode() is blocking CPU work; callers must run it
via asyncio.to_thread(...), same pattern already used for
file_extractor.extract_text() in chat.py.
"""

import os
import threading
from typing import List

from dotenv import load_dotenv

load_dotenv(override=True)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # re-check inside the lock
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch-embed multiple texts (document chunk ingestion). Blocking — call
    via asyncio.to_thread from async code."""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, batch_size=16, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> List[float]:
    """Embed a single query string (retrieval-at-chat-time). Blocking — call
    via asyncio.to_thread from async code."""
    model = _get_model()
    vector = model.encode(text, show_progress_bar=False)
    return vector.tolist()
