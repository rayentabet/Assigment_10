"""Robot 3D visualization specialist."""

from langchain.agents import create_agent

from app.models import visualization_model
from tools.model_tools import render_model, save_model

VISUALIZATION_PROMPT = """You create simple robot models as a list of parts.
Use millimeters for every dimension and degrees for rotation.
Each part is a box, cylinder, or sphere with a position [x, y, z] (its center,
z is up) and an optional rotation [x, y, z] (both default to [0, 0, 0]).
Add the chassis, wheels, sensors, battery, and controller when requested, sized
and positioned so they do not overlap unless that is physically correct (for
example wheels sitting flush against the chassis).
Use save_model with the complete part list, then render_model on the path it
returns to create the preview.
Return a concise final summary and rendering errors, but do not expose hidden
reasoning, scratch work, chain-of-thought, or local preview paths. The UI receives
the rendered preview separately.
"""


async def build_agent():
    """Create the visualization agent with only its deterministic model tools."""

    return create_agent(
        model=visualization_model(),
        tools=[save_model, render_model],
        system_prompt=VISUALIZATION_PROMPT,
    )
