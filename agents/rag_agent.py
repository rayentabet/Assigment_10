"""RAG specialist that receives tools from the MCP server."""

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings

RAG_PROMPT = """You are the robotics documentation specialist.
Use the MCP tools for every documentation question.
Use search_documents when evidence is requested.
Use answer_question when the user wants an answer.
After retrieval, inspect the returned contexts. When a relevant context has a
non-empty image_path, call show_image for that image even if the user did not
explicitly request it. Do not show irrelevant images or invent image paths.
Never invent information that is missing from the retrieved documents.
Keep source names and locations in your answer.
"""


async def create_rag_agent():
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
            }
        }
    )
    tools = await client.get_tools(server_name="arduino_rag")
    model = ChatGoogleGenerativeAI(model=settings.rag_model, temperature=0)

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=RAG_PROMPT,
    )
