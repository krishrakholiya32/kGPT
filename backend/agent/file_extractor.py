"""
File text extractor for kGPT attachments.
Supports: PDF (pymupdf), DOCX (python-docx), JPEG/PNG (Groq vision).
"""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

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
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set — cannot describe image content.")
    from groq import Groq
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    b64 = base64.b64encode(data).decode()
    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": (
                    "Describe everything visible in this image in full detail — "
                    "including all text, numbers, labels, charts, diagrams, or visual content. "
                    "Be thorough and precise."
                )},
            ],
        }],
        max_tokens=1024,
    )
    return resp.choices[0].message.content
