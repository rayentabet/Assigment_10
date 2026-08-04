import os

import httpx
import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient


@pytest.mark.asyncio
async def test_rag_mcp_tools_are_available() -> None:
    url = os.environ.get("MCP_INTEGRATION_TEST_URL")
    if not url:
        pytest.skip("Set MCP_INTEGRATION_TEST_URL to test the Docker MCP server")
    token = os.environ.get("MCP_AUTH_TOKEN")
    if not token:
        pytest.skip("Set MCP_AUTH_TOKEN to test the protected Docker MCP server")

    client = MultiServerMCPClient(
        {
            "rag": {
                "transport": "streamable_http",
                "url": url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )

    tools = await client.get_tools(server_name="rag")
    tool_names = {tool.name for tool in tools}

    assert tool_names == {"search_documents", "answer_question", "show_image"}


@pytest.mark.asyncio
async def test_rag_mcp_rejects_an_unauthenticated_request() -> None:
    url = os.environ.get("MCP_INTEGRATION_TEST_URL")
    if not url:
        pytest.skip("Set MCP_INTEGRATION_TEST_URL to test the Docker MCP server")

    async with httpx.AsyncClient() as client:
        response = await client.get(url)

    assert response.status_code == 401
