"""
LLM Factory Module for kGPT.

Single provider: Groq (requires GROQ_API_KEY).
Config is re-read from .env on every call so changes take effect on the
next request without a restart.
"""

import os

from dotenv import load_dotenv


def _env() -> dict:
    load_dotenv(override=True)
    return {
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "groq_key": os.getenv("GROQ_API_KEY", ""),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    }


def candidate_providers() -> list:
    cfg = _env()
    return ["groq"] if cfg["groq_key"] else []


def build_llm(provider: str):
    cfg = _env()
    if provider == "groq":
        if not cfg["groq_key"]:
            raise ValueError("GROQ_API_KEY is not set.")
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=cfg["groq_model"],
            groq_api_key=cfg["groq_key"],
            temperature=cfg["temperature"],
        )
    raise ValueError(f"Unknown provider '{provider}'.")


def get_llm():
    return build_llm("groq")
