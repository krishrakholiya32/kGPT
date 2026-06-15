"""
Conversation Memory Module for kGPT.

Manages per-user conversation history using LangChain's
ConversationBufferWindowMemory with a sliding window of the last k exchanges.
"""

from typing import Dict, List

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import BaseMessage

_memories: Dict[str, ConversationBufferWindowMemory] = {}


def get_memory(user_id: str) -> ConversationBufferWindowMemory:
    """
    Returns the conversation memory for a given user. Creates a new memory
    instance with a window of 10 exchanges if one doesn't exist yet.

    Args:
        user_id: Unique identifier for the user.

    Returns:
        A ConversationBufferWindowMemory instance for the user.
    """
    if user_id not in _memories:
        _memories[user_id] = ConversationBufferWindowMemory(
            k=10,
            return_messages=True,
            memory_key="chat_history",
            input_key="input",
            output_key="output",
        )
    return _memories[user_id]


def clear_memory(user_id: str) -> None:
    """
    Clears the conversation history for a given user. If no memory exists
    for the user, this is a no-op.

    Args:
        user_id: Unique identifier for the user.
    """
    if user_id in _memories:
        _memories[user_id].clear()


def get_history(user_id: str) -> List[BaseMessage]:
    """
    Returns the list of stored chat messages for a given user.

    Args:
        user_id: Unique identifier for the user.

    Returns:
        A list of BaseMessage objects representing the conversation history.
        Returns an empty list if no history exists for the user.
    """
    if user_id not in _memories:
        return []

    memory = _memories[user_id]
    memory_variables = memory.load_memory_variables({})
    messages: List[BaseMessage] = memory_variables.get("chat_history", [])
    return messages
