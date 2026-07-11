"""
File text extractor for kGPT attachments.
Supports: PDF (pymupdf), DOCX (python-docx), JPEG/PNG (Gemini vision primary,
Groq vision fallback — same provider order as the main chat LLM).
"""
import base64
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from backend.agent.llm import _all_gemini_keys, _all_groq_keys

IMAGE_DESCRIBE_PROMPT = (
    "Describe everything visible in this image in full detail — "
    "including all text, numbers, labels, charts, diagrams, or visual content. "
    "Be thorough and precise."
)

MAX_CONTEXT_CHARS = 12_000  # ~3k tokens, keeps prompts manageable
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".docx"}


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: jpg, png, pdf, docx.")
    if ext == ".pdf":
        text = _extract_pdf(file_bytes)
    elif ext == ".docx":
        text = _extract_docx(file_bytes)
    else:
        text = _extract_image(file_bytes, ext)
    return text[:MAX_CONTEXT_CHARS]


def _extract_pdf(data: bytes) -> str:
    import fitz  # pymupdf
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text() for page in doc).strip()


def _extract_docx(data: bytes) -> str:
    from io import BytesIO
    import docx
    doc = docx.Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_image(data: bytes, ext: str) -> str:
    load_dotenv(override=True)
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    b64 = base64.b64encode(data).decode()

    # Rotate through every configured key (not just the first) for both
    # providers, same resilience the main chat LLM gets in llm.py — a single
    # rate-limited/revoked key shouldn't fail file-upload descriptions outright.
    last_exc: Optional[Exception] = None
    for key in _all_gemini_keys():
        try:
            return _gemini_vision(b64, mime, key)
        except Exception as exc:
            last_exc = exc
            print(f"[kGPT] Gemini vision key ...{key[-6:]} failed, trying next: {exc}")

    for key in _all_groq_keys():
        try:
            return _groq_vision(b64, mime, key)
        except Exception as exc:
            last_exc = exc
            print(f"[kGPT] Groq vision key ...{key[-6:]} failed, trying next: {exc}")

    if last_exc is not None:
        raise ValueError(f"All configured vision providers failed to describe the image: {last_exc}")
    raise ValueError("Neither GEMINI_API_KEY(S) nor GROQ_API_KEY(S) is set — cannot describe image content.")


def _gemini_vision(b64: str, mime: str, key: str) -> str:
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime, "data": b64}},
            {"text": IMAGE_DESCRIBE_PROMPT},
        ]}]
    }
    resp = httpx.post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq_vision(b64: str, mime: str, key: str) -> str:
    from groq import Groq
    model = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
    client = Groq(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": IMAGE_DESCRIBE_PROMPT},
            ],
        }],
        max_tokens=1024,
    )
    return resp.choices[0].message.content
