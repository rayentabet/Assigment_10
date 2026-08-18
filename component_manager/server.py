"""A2A HTTP server exposing the Component Manager agent.

Run with:
    PYTHONPATH=. component_manager/.venv/bin/uvicorn component_manager.server:app \
        --host 0.0.0.0 --port 8002

This publishes the Agent Card at /.well-known/agent-card.json and serves the
A2A JSON-RPC endpoints System A's procurement tools call into (Phase 3).
"""

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from component_manager.agent import root_agent
from component_manager.config import settings

app = to_a2a(root_agent, host=settings.advertised_host, port=settings.port)
