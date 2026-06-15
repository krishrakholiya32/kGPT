"""
Tools & Agent Executor Module for kGPT.
Defines web search, SQL, code execution tools and the agent executor.
"""

import os
from typing import List

from dotenv import load_dotenv
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_experimental.tools import PythonREPLTool
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.tools import BaseTool
from langchain_core.prompts import PromptTemplate

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./database/data.db")

KGPT_SYSTEM_PROMPT = """You are kGPT, a helpful, knowledgeable, and versatile AI assistant.

You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Important guidelines:
- Always be helpful, accurate, and concise.
- If you don't know something, say so honestly.
- Use the web search tool for up-to-date information.
- Use SQL tools when the user asks about database data.
- Use Python REPL for calculations, data processing, or code execution.

Begin!

Question: {input}
Thought:{agent_scratchpad}"""


def _get_search_tool() -> BaseTool:
    return DuckDuckGoSearchResults(
        name="web_search",
        description=(
            "Useful for searching the web for current information, news, "
            "facts, or any topic. Input should be a search query string."
        ),
        num_results=5,
    )


def _get_python_repl_tool() -> BaseTool:
    return PythonREPLTool(
        name="python_repl",
        description=(
            "A Python shell. Use this to execute Python code. "
            "Input should be a valid Python command. "
            "Print output with print(...)."
        ),
    )


def _get_sql_tools(llm) -> List[BaseTool]:
    try:
        db = SQLDatabase.from_uri(DATABASE_URL)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        return toolkit.get_tools()
    except Exception:
        return []


def get_tools(llm) -> List[BaseTool]:
    tools: List[BaseTool] = []
    tools.append(_get_search_tool())
    tools.append(_get_python_repl_tool())
    tools.extend(_get_sql_tools(llm))
    return tools


def create_agent_executor(llm) -> AgentExecutor:
    tools = get_tools(llm)
    prompt = PromptTemplate(
        template=KGPT_SYSTEM_PROMPT,
        input_variables=["input", "agent_scratchpad"],
        partial_variables={
            "tools": "\n".join([f"- {t.name}: {t.description}" for t in tools]),
            "tool_names": ", ".join([t.name for t in tools]),
        },
    )
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=10,
        return_intermediate_steps=False,
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


def run_sql_agent(question: str, llm) -> str:
    """Run a natural language SQL query."""
    try:
        executor = create_agent_executor(llm)
        result = executor.invoke({"input": f"Using the database, answer: {question}"})
        return result.get("output", str(result))
    except Exception as e:
        return f"SQL agent error: {e}"


def run_code_execution(question: str, llm) -> str:
    """Write and execute Python code to answer a question."""
    try:
        executor = create_agent_executor(llm)
        result = executor.invoke({"input": f"Write and run Python code to: {question}"})
        return result.get("output", str(result))
    except Exception as e:
        return f"Code execution error: {e}"
