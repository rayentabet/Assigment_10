"""MCP tools for the existing Arduino RAG."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.utilities.types import Image

from mcp_server.qdrant_bootstrap import ensure_qdrant_collection

RAG_PATH = Path(
    os.environ.get("RAG_PATH", Path(__file__).resolve().parents[1] / "rag")
).resolve()

load_dotenv(override=False)

from rag.adapter import adapter  # noqa: E402
from rag.retrieval import search  # noqa: E402

MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
auth = None
if MCP_AUTH_TOKEN:
    auth = StaticTokenVerifier(
        tokens={
            MCP_AUTH_TOKEN: {
                "client_id": "arduino-rag-clients",
                "scopes": ["mcp:access"],
            }
        },
        required_scopes=["mcp:access"],
    )

mcp = FastMCP("Arduino RAG", auth=auth)


@mcp.tool()
def search_documents(query: str, limit: int = 5) -> list[dict]:
    """Search the Arduino documentation."""

    return search(query, limit=limit, modality="text")


@mcp.tool()
def answer_question(question: str) -> dict:
    """Answer a question using the Arduino documentation."""

    result = adapter.answer(question, record_id="mcp")

    contexts = [
        {
            "text": context.text,
            "source": context.source_id,
            "location": context.location,
            "image_path": context.image_path,
        }
        for context in result.contexts
    ]

    return {"answer": result.answer, "contexts": contexts}


@mcp.tool()
def show_image(image_path: str) -> Image:
    """Display an image returned by the RAG."""

    path = (RAG_PATH / image_path).resolve()

    if RAG_PATH not in path.parents:
        raise ValueError("Invalid image path.")
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    return Image(path=path)


@mcp.resource("corpus://metadata")
def corpus_metadata() -> str:
    """Describe the indexed Arduino and robotics corpus."""

    return json.dumps(
        {
            "name": "Arduino and Robotics Documentation",
            "topics": [
                "Arduino boards",
                "sensors",
                "wiring",
                "robotics projects",
                "component specifications",
            ],
            "content": [
                "PDF documents",
                "Markdown documents",
                "OCR text",
                "image captions",
            ],
            "retrieval": [
                "vector search",
                "BM25 keyword search",
                "reranking",
            ],
        },
        indent=2,
    )


if __name__ == "__main__":
    ensure_qdrant_collection()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        if not MCP_AUTH_TOKEN:
            raise RuntimeError("MCP_AUTH_TOKEN must be set for the HTTP transport")
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
    else:
        mcp.run(transport=transport)
