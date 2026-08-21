"""RAG specialist that receives tools from the MCP server."""

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from agents import cached_agent
from app.config import settings
from app.models import rag_model

RAG_PROMPT = """You are the robotics documentation specialist.
Use the MCP tools for every documentation question.
Use answer_question to retrieve evidence and produce the grounded answer.
After retrieval, inspect the returned contexts. When a relevant context has a
non-empty image_path, call show_image for that image even if the user did not
explicitly request it. Do not show irrelevant images or invent image paths.
Never invent information that is missing from the retrieved documents.
Keep source names and locations in your answer.
Return only the grounded final answer and concise supporting facts. Do not expose
hidden reasoning, scratch work, or chain-of-thought.
"""


@cached_agent
async def build_agent():
    """Create the RAG agent and load its tools through MCP."""

    if not settings.mcp_auth_token:
        raise RuntimeError("MCP_AUTH_TOKEN is required to connect to the MCP server")

    client = MultiServerMCPClient(
        {
            "arduino_rag": {
                "transport": "streamable_http",
                "url": settings.mcp_server_url,
                "headers": {
                    "Authorization": f"Bearer {settings.mcp_auth_token}",
                },
                "timeout": settings.mcp_timeout_seconds,
                "sse_read_timeout": settings.mcp_timeout_seconds,
            }
        }
    )
    tools = await client.get_tools(server_name="arduino_rag")
    tools = [tool for tool in tools if tool.name in {"answer_question", "show_image"}]

    return create_agent(
        model=rag_model(),
        tools=tools,
        system_prompt=RAG_PROMPT,
    )
