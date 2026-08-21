"""Wiring and pin management specialist."""

from langchain.agents import create_agent

from app.models import wiring_model
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
Always call format_wiring_plan and base your answer's table on its output — never
hand-write the pin table yourself, even for a single component, since only the
tool's output is guaranteed to match what was actually validated.
Report unallocated components and validation conflicts or warnings plainly; do not
hide them. Return the final wiring table and a short summary. Do not expose hidden
reasoning, scratch work, or chain-of-thought.

Wiring only: never write, include, or sketch firmware/driving code in your answer,
even if the task also mentions code. You have no code tools, and code written here
skips the coding specialist's validation and the human approval it requires before
anything is saved. If the task asks for both wiring and code, deliver only the
wiring plan; a separate specialist handles the code in the next step.
"""


async def build_agent(existing_assignments: dict | None = None):
    """Create the wiring agent with only its deterministic pin tools."""

    allocate_pins = make_allocator(existing_assignments)
    return create_agent(
        model=wiring_model(),
        tools=[
            get_board,
            get_component,
            allocate_pins,
            validate_wiring,
            format_wiring_plan,
        ],
        system_prompt=WIRING_PROMPT,
    )
