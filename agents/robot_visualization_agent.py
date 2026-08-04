"""Robot OpenSCAD visualization specialist."""

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings
from tools.openscad_tools import render_openscad, save_openscad

VISUALIZATION_PROMPT = """You create simple robot models with OpenSCAD.
Use millimeters for every dimension.
Use basic cubes, cylinders, spheres, translate, and rotate.
Add the chassis, wheels, sensors, battery, and controller when requested.
Use save_openscad to save the .scad file.
Use render_openscad to create the PNG preview.
Return the model path, preview path, assumptions, and rendering errors.
"""


async def create_robot_visualization_agent():
    """Create the visualization agent with only OpenSCAD tools."""


    model = ChatGoogleGenerativeAI(
        model=settings.visualization_model,
        temperature=0,
    )
    return create_agent(
        model=model,
        tools=[save_openscad, render_openscad],
        system_prompt=VISUALIZATION_PROMPT,
    )
