"""
Tools Module for kGPT.
Defines the web search tool used for the 'web' chat mode.

The primary search path uses the maintained ``ddgs`` package (falling back to the
legacy ``duckduckgo_search`` name) directly. A secondary LangChain-based fallback
is kept but imported lazily so the module still loads even though the LangChain
packages have been removed from the default dependency set.
"""


def _langchain_fallback(query: str) -> str:
    """Best-effort fallback via LangChain's DuckDuckGo tool, if it happens to be
    installed. Returns '' if LangChain is unavailable or produced nothing."""
    try:
        from langchain_community.tools import DuckDuckGoSearchResults

        tool = DuckDuckGoSearchResults(
            name="web_search",
            description=(
                "Useful for searching the web for current information, news, "
                "facts, or any topic. Input should be a search query string."
            ),
            num_results=5,
        )
        raw = tool.run(query)
        if raw and raw.strip():
            return raw
    except Exception:
        pass
    return ""


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
        fallback = _langchain_fallback(query)
        if fallback:
            return fallback
        return f"Search error: {e}"

    if not results:
        return "No web results were found for this query."
    return "\n\n".join(results)
