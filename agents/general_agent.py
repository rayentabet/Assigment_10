"""General-purpose specialist without tools."""

from langchain.agents import create_agent
from langchain_groq import ChatGroq

from app.config import settings

GENERAL_PROMPT = """You are the general-purpose specialist.
Answer ordinary questions clearly and briefly.
Do not claim to search the robotics corpus or create files.
Return only the final answer. Do not expose hidden reasoning, scratch work, or
chain-of-thought.
"""


async def create_general_agent():
    """Create the tool-free general agent."""

    model = ChatGroq(model=settings.general_model, temperature=0)
    return create_agent(model=model, tools=[], system_prompt=GENERAL_PROMPT)
