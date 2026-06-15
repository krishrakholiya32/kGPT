"""
LLM Factory Module for kGPT.

Cloud providers:
    gemini -> Google Gemini  (requires GEMINI_API_KEY)
    groq   -> Groq            (requires GROQ_API_KEY)

Provider selection:
    LLM_PROVIDER = gemini | groq   (defaults to gemini)

Config is re-read from .env on every call, so changes take effect on the next
request with no restart. `candidate_providers()` returns the preferred provider
followed by any available fallback, so callers can transparently retry on
failure (e.g. a quota / 429 error) using another provider.

Provider packages are imported lazily, so you only need the integration you use.
"""

import os

from dotenv import load_dotenv

_VALID = ("gemini", "groq")


def _env() -> dict:
    """Re-read .env on every call so changes apply without a restart."""
    load_dotenv(override=True)
    return {
        "provider": os.getenv("LLM_PROVIDER", "").strip().lower(),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "gemini_key": os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "groq_key": os.getenv("GROQ_API_KEY", ""),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    }


def resolve_provider() -> str:
    """Return the preferred provider: 'gemini' or 'groq'."""
    cfg = _env()
    if cfg["provider"] in _VALID:
        return cfg["provider"]
    return "gemini"


def _available(provider: str, cfg: dict) -> bool:
    if provider == "gemini":
        return bool(cfg["gemini_key"])
    if provider == "groq":
        return bool(cfg["groq_key"])
    return False


def candidate_providers() -> list:
    """Preferred provider first, then any available fallback (ordered)."""
    cfg = _env()
    preferred = resolve_provider()
    order = [preferred] + [p for p in _VALID if p != preferred]
    return [p for p in order if p == preferred or _available(p, cfg)]


def build_llm(provider: str):
    """Construct a chat model for a specific provider (raises if misconfigured)."""
    cfg = _env()

    if provider == "gemini":
        if not cfg["gemini_key"]:
            raise ValueError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=cfg["gemini_model"],
            google_api_key=cfg["gemini_key"],
            temperature=cfg["temperature"],
        )

    if provider == "groq":
        if not cfg["groq_key"]:
            raise ValueError("GROQ_API_KEY is not set.")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=cfg["groq_model"],
            groq_api_key=cfg["groq_key"],
            temperature=cfg["temperature"],
        )

    raise ValueError(
        f"Unknown LLM provider '{provider}'. Use LLM_PROVIDER=gemini|groq."
    )


def get_llm():
    """Return a chat model for the preferred provider."""
    return build_llm(resolve_provider())


def build_vision_llm():
    """Construct a vision-capable chat model for image understanding.

    Uses Groq's natively-multimodal Llama 4 Scout by default (free tier).
    Requires GROQ_API_KEY. Override the model with GROQ_VISION_MODEL.
    """
    cfg = _env()
    if not cfg["groq_key"]:
        raise ValueError("GROQ_API_KEY is required for image understanding.")
    from langchain_groq import ChatGroq

    model = os.getenv(
        "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
    )
    return ChatGroq(
        model=model,
        groq_api_key=cfg["groq_key"],
        temperature=cfg["temperature"],
    )