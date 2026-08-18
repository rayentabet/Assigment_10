"""Coding specialist."""

from langchain.agents import create_agent
from langchain_groq import ChatGroq

from app.config import settings
from tools.code_tools import save_code, validate_code

CODING_PROMPT = """You are the coding specialist.
Write simple and readable code.
If the user only asks for an explanation, review, or why existing code fails,
answer directly and do not call any tool.
Only use save_code when the user asks you to create, fix, save, or produce code.
When saving, pass both required arguments: filename and the complete code. Use a
plain filename ending in .py, .ino, .cpp, .h, .js, or .txt with no folder. Then
call validate_code with that exact filename and return the path and validation result.
Do not write tool-call markup or place explanations inside tool arguments.
Return only the final code/result and concise explanation. Do not expose hidden
reasoning, scratch work, or chain-of-thought.
"""


async def build_agent():
    """Create the coding agent with only its allowed tools."""

    model = ChatGroq(model=settings.code_model, temperature=0)
    return create_agent(
        model=model,
        tools=[save_code, validate_code],
        system_prompt=CODING_PROMPT,
    )
