"""
Tools Module for kGPT.
Defines the web search tool used for the 'web' chat mode.
"""

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_core.tools import BaseTool


def _get_search_tool() -> BaseTool:
    return DuckDuckGoSearchResults(
        name="web_search",
        description=(
            "Useful for searching the web for current information, news, "
            "facts, or any topic. Input should be a search query string."
        ),
        num_results=5,
    )


def run_web_search(query: str) -> str:
    """Search the web (DuckDuckGo) and return a formatted results string."""
    results = []
    try:
        try:
            from ddgs import DDGS  # maintained package name
        except ImportError:
            from duckduckgo_search import DDGS  # legacy name

        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=6):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "") or r.get("url", "")
                results.append(f"- {title}\n  {body}\n  {href}")
    except Exception as e:
        try:
            raw = _get_search_tool().run(query)
            if raw and raw.strip():
                return raw
        except Exception:
            pass
        return f"Search error: {e}"

    if not results:
        return "No web results were found for this query."
    return "\n\n".join(results)
