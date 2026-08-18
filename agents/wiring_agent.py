"""Wiring and pin management specialist."""

from langchain.agents import create_agent
from langchain_groq import ChatGroq

from app.config import settings
from tools.wiring_tools import (
    format_wiring_plan,
    get_board,
    get_component,
    make_allocator,
    validate_wiring,
)

WIRING_PROMPT = """You are the wiring and pin management specialist.
For every request, call tools in this exact order and never invent pin numbers:
1. get_board for the target board.
2. get_component for each requested component.
3. allocate_pins with the board and only the new components requested. Existing
   assignments are protected internally by the system and are not tool arguments.
4. validate_wiring with the board and the assignments returned by allocate_pins.
5. format_wiring_plan with the board, those assignments, and the validation result.
Report unallocated components and validation conflicts or warnings plainly; do not
hide them. Return the final wiring table and a short summary. Do not expose hidden
reasoning, scratch work, or chain-of-thought.
"""


async def build_agent(existing_assignments: dict | None = None):
    """Create the wiring agent with only its deterministic pin tools."""

    model = ChatGroq(model=settings.wiring_model, temperature=0)
    allocate_pins = make_allocator(existing_assignments)
    return create_agent(
        model=model,
        tools=[
            get_board,
            get_component,
            allocate_pins,
            validate_wiring,
            format_wiring_plan,
        ],
        system_prompt=WIRING_PROMPT,
    )
