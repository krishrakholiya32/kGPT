"""
LLM Factory for kGPT — multi-key rotation, Groq primary + Gemini fallback.
Config re-read from .env on every call so key changes take effect without restart.
"""

import os
from dotenv import load_dotenv


def _env() -> dict:
    load_dotenv(override=True)
    return {
        "temperature":   float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "groq_model":    os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "gemini_model":  os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
    }


def _all_groq_keys() -> list[str]:
    load_dotenv(override=True)
    keys: list[str] = []
    k = os.getenv("GROQ_API_KEY", "")
    if k:
        keys.append(k)
    extras = os.getenv("GROQ_API_KEYS", "")
    if extras:
        keys += [x.strip() for x in extras.split(",") if x.strip()]
    return keys


def _all_gemini_keys() -> list[str]:
    load_dotenv(override=True)
    keys: list[str] = []
    k = os.getenv("GEMINI_API_KEY", "")
    if k:
        keys.append(k)
    extras = os.getenv("GEMINI_API_KEYS", "")
    if extras:
        keys += [x.strip() for x in extras.split(",") if x.strip()]
    return keys


def candidate_providers() -> list[str]:
    """Return ordered list: all Groq keys first, then all Gemini keys."""
    providers: list[str] = []
    for i, k in enumerate(_all_groq_keys()):
        if k:
            providers.append(f"groq:{i}")
    for i, k in enumerate(_all_gemini_keys()):
        if k:
            providers.append(f"gemini:{i}")
    return providers


def build_llm(provider: str):
    cfg = _env()
    kind, _, idx_str = provider.partition(":")
    idx = int(idx_str) if idx_str else 0

    if kind == "groq":
        keys = _all_groq_keys()
        if idx >= len(keys) or not keys[idx]:
            raise ValueError(f"No Groq key at index {idx}")
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=cfg["groq_model"],
            groq_api_key=keys[idx],
            temperature=cfg["temperature"],
        )

    if kind == "gemini":
        keys = _all_gemini_keys()
        if idx >= len(keys) or not keys[idx]:
            raise ValueError(f"No Gemini key at index {idx}")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=cfg["gemini_model"],
            google_api_key=keys[idx],
            temperature=cfg["temperature"],
        )

    raise ValueError(f"Unknown provider '{provider}'")


def get_llm():
    providers = candidate_providers()
    if not providers:
        raise ValueError("No LLM provider configured — set GROQ_API_KEY in .env")
    return build_llm(providers[0])
