"""
LLM Factory for kGPT — multi-key rotation, Groq primary + Gemini fallback.

Rewritten to call the Groq and Gemini HTTP APIs directly with ``httpx`` instead
of going through LangChain. The public shape the rest of the app depends on is
preserved:

- ``candidate_providers()`` returns the ordered provider list
  (all Groq keys first, then all Gemini keys) exactly as before.
- ``build_llm(provider)`` returns an object with:
    * ``await client.ainvoke(prompt, system=None)`` -> full text (non-streaming)
    * ``async for piece in client.astream(prompt, system=None)`` -> text chunks
- ``get_llm()`` returns the first provider's client.

Config is re-read from ``.env`` on every call so key changes take effect without
a restart (same behaviour as before).
"""

import json
import os
from typing import AsyncIterator, Optional

import httpx
from dotenv import load_dotenv

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


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


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin async wrapper over a single Groq or Gemini API key.

    ``ainvoke`` returns the complete response text; ``astream`` yields text
    chunks as they arrive over Server-Sent Events.
    """

    def __init__(self, kind: str, api_key: str, model: str, temperature: float):
        self.kind = kind
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    # ---- Groq (OpenAI-compatible) ----------------------------------------

    def _groq_messages(self, prompt: str, system: Optional[str]) -> list[dict]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _groq_invoke(self, prompt: str, system: Optional[str]) -> str:
        payload = {
            "model": self.model,
            "messages": self._groq_messages(prompt, system),
            "temperature": self.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(GROQ_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""

    async def _groq_stream(self, prompt: str, system: Optional[str]) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": self._groq_messages(prompt, system),
            "temperature": self.temperature,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", GROQ_URL, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    try:
                        piece = obj["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError):
                        piece = None
                    if piece:
                        yield piece

    # ---- Gemini ----------------------------------------------------------

    def _gemini_body(self, prompt: str, system: Optional[str]) -> dict:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    async def _gemini_invoke(self, prompt: str, system: Optional[str]) -> str:
        url = f"{GEMINI_BASE}/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=self._gemini_body(prompt, system))
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)

    async def _gemini_stream(self, prompt: str, system: Optional[str]) -> AsyncIterator[str]:
        url = f"{GEMINI_BASE}/{self.model}:streamGenerateContent?alt=sse"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=self._gemini_body(prompt, system)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    try:
                        parts = obj["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError):
                        continue
                    for p in parts:
                        piece = p.get("text")
                        if piece:
                            yield piece

    # ---- Public API ------------------------------------------------------

    async def ainvoke(self, prompt: str, system: Optional[str] = None) -> str:
        if self.kind == "groq":
            return await self._groq_invoke(prompt, system)
        if self.kind == "gemini":
            return await self._gemini_invoke(prompt, system)
        raise ValueError(f"Unknown provider kind '{self.kind}'")

    async def astream(self, prompt: str, system: Optional[str] = None) -> AsyncIterator[str]:
        if self.kind == "groq":
            async for piece in self._groq_stream(prompt, system):
                yield piece
        elif self.kind == "gemini":
            async for piece in self._gemini_stream(prompt, system):
                yield piece
        else:
            raise ValueError(f"Unknown provider kind '{self.kind}'")


def build_llm(provider: str) -> LLMClient:
    cfg = _env()
    kind, _, idx_str = provider.partition(":")
    idx = int(idx_str) if idx_str else 0

    if kind == "groq":
        keys = _all_groq_keys()
        if idx >= len(keys) or not keys[idx]:
            raise ValueError(f"No Groq key at index {idx}")
        return LLMClient("groq", keys[idx], cfg["groq_model"], cfg["temperature"])

    if kind == "gemini":
        keys = _all_gemini_keys()
        if idx >= len(keys) or not keys[idx]:
            raise ValueError(f"No Gemini key at index {idx}")
        return LLMClient("gemini", keys[idx], cfg["gemini_model"], cfg["temperature"])

    raise ValueError(f"Unknown provider '{provider}'")


def get_llm() -> LLMClient:
    providers = candidate_providers()
    if not providers:
        raise ValueError("No LLM provider configured — set GROQ_API_KEY in .env")
    return build_llm(providers[0])
