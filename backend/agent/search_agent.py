"""
Corrective web-search agent for kGPT's web-search chat mode, built with LangGraph.

Replaces the old single-shot "search once, answer with whatever came back" flow
with a small, bounded loop: search -> grade the results for relevance -> if
insufficient, refine the query and search again (capped at one retry) -> hand
off a final, good search-results string to the caller.

Deliberately scoped: this is the one place in kGPT that reintroduces
LangChain/LangGraph (see requirements.txt's comment) -- general chat, RAG
document/memory retrieval, and the multi-key provider rotation are untouched
and still framework-free. `KgptChatModel` wraps the existing `LLMClient`
(backend/agent/llm.py) rather than reimplementing multi-key rotation on top
of an official provider integration, so that already-working behavior isn't
duplicated.

Token-level streaming of the *final answer* stays on the existing, proven
`LLMClient.astream()` path in chat.py -- this module only orchestrates the
search-and-grade loop (which is short, single-shot LLM calls, not something
that benefits from token streaming) and yields status events plus a final
"ready" event carrying the search results the caller uses to build and
stream the actual answer.
"""

import asyncio
import functools
from typing import Any, AsyncIterator, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, START, StateGraph

from backend.agent.tools import run_web_search

MAX_SEARCH_ATTEMPTS = 2  # bounded: at most one refine-and-retry


class KgptChatModel(BaseChatModel):
    """Thin LangChain BaseChatModel adapter around kGPT's existing LLMClient,
    so LangGraph nodes can call `.ainvoke([...])` like any other chat model
    while actually reusing the already-working multi-key rotation and
    `.env` hot-reload behavior in llm.py, instead of re-solving that problem
    with an official langchain-google-genai/langchain-groq integration."""

    llm_client: Any  # backend.agent.llm.LLMClient, not typed directly to avoid a pydantic/BaseChatModel field-validation mismatch

    @property
    def _llm_type(self) -> str:
        return "kgpt-llm-client"

    @staticmethod
    def _messages_to_prompt(messages: list[BaseMessage]) -> tuple[Optional[str], str]:
        system_parts = []
        human_parts = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system_parts.append(str(m.content))
            else:
                human_parts.append(str(m.content))
        system = "\n".join(system_parts) if system_parts else None
        prompt = "\n".join(human_parts)
        return system, prompt

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        system, prompt = self._messages_to_prompt(messages)
        text = await self.llm_client.ainvoke(prompt, system=system)
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("KgptChatModel is async-only; call ainvoke, not invoke.")


async def _web_search_tool(query: str) -> str:
    return await asyncio.to_thread(run_web_search, query)


class _SearchState(TypedDict):
    user_message: str
    history_text: str
    search_query: str
    search_results: str
    attempts: int
    sufficient: bool


async def _node_resolve_query(state: _SearchState, model: KgptChatModel) -> dict:
    user_message = state["user_message"]
    history_text = state["history_text"]
    if not history_text or len(user_message.split()) > 6:
        return {"search_query": user_message}
    prompt = (
        f"Given this conversation history:\n{history_text}\n"
        f"The user just said: \"{user_message}\"\n"
        f"Rewrite their message as a single, self-contained web search query "
        f"(no explanation, just the query):"
    )
    result = await model.ainvoke([SystemMessage(prompt)])
    return {"search_query": result.content.strip().strip('"')}


async def _node_search(state: _SearchState) -> dict:
    results = await _web_search_tool(state["search_query"])
    return {"search_results": results, "attempts": state["attempts"] + 1}


_GRADE_SYSTEM = (
    "You grade whether web search results are sufficient to answer a user's "
    "question. Reply with exactly one word: 'yes' if the results contain enough "
    "relevant information to answer, or 'no' if they're irrelevant, empty, or "
    "clearly insufficient. No explanations, punctuation, or extra words."
)


async def _node_grade(state: _SearchState, model: KgptChatModel) -> dict:
    prompt = (
        f"Question: {state['user_message']}\n\n"
        f"Search results:\n{state['search_results']}\n\n"
        f"Are these results sufficient to answer the question?"
    )
    result = await model.ainvoke([SystemMessage(_GRADE_SYSTEM), SystemMessage(prompt)])
    answer = result.content.strip().lower()
    return {"sufficient": answer.startswith("y")}


async def _node_refine_query(state: _SearchState, model: KgptChatModel) -> dict:
    prompt = (
        f"A web search for the query \"{state['search_query']}\" did not return "
        f"results relevant enough to answer this question: \"{state['user_message']}\"\n"
        f"Write a better, more specific or differently-phrased search query "
        f"(no explanation, just the query):"
    )
    result = await model.ainvoke([SystemMessage(prompt)])
    return {"search_query": result.content.strip().strip('"')}


def _after_grade(state: _SearchState) -> str:
    if state["sufficient"] or state["attempts"] >= MAX_SEARCH_ATTEMPTS:
        return "done"
    return "refine"


def _build_graph(model: KgptChatModel):
    graph = StateGraph(_SearchState)
    graph.add_node("resolve_query", functools.partial(_node_resolve_query, model=model))
    graph.add_node("search", _node_search)
    graph.add_node("grade", functools.partial(_node_grade, model=model))
    graph.add_node("refine_query", functools.partial(_node_refine_query, model=model))

    graph.add_edge(START, "resolve_query")
    graph.add_edge("resolve_query", "search")
    graph.add_edge("search", "grade")
    graph.add_conditional_edges("grade", _after_grade, {"done": END, "refine": "refine_query"})
    graph.add_edge("refine_query", "search")
    return graph.compile()


_STATUS_TEXT = {
    "resolve_query": "Preparing search…",
    "search": "Searching the web…",
    "grade": "Checking whether the results answer your question…",
    "refine_query": "Refining the search…",
}


async def run_search_agent(llm_client, user_message: str, history_text: str) -> AsyncIterator[dict]:
    """Runs the corrective search loop. Yields {"type": "status", "text": ...}
    as each node completes, and a final {"type": "ready", "search_query": ...,
    "search_results": ...} once the loop is done (either the results were
    graded sufficient, or MAX_SEARCH_ATTEMPTS was hit). The caller builds and
    streams the actual answer from the "ready" event -- this function never
    calls the LLM in streaming mode itself."""
    model = KgptChatModel(llm_client=llm_client)
    graph = _build_graph(model)
    state: dict = {
        "user_message": user_message,
        "history_text": history_text,
        "search_query": "",
        "search_results": "",
        "attempts": 0,
        "sufficient": False,
    }
    async for update in graph.astream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            state.update(node_output)
            status_text = _STATUS_TEXT.get(node_name)
            if status_text:
                yield {"type": "status", "text": status_text}
    yield {"type": "ready", "search_query": state["search_query"], "search_results": state["search_results"]}
