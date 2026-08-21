# System architecture

This diagram shows the full deployed topology — five containers plus
external services. It complements, and does not replace,
[`langgraph_workflow.svg`](langgraph_workflow.svg), which shows only the
internal node graph *inside* `agent-system-a`.

```mermaid
graph TB
    User((Browser))

    subgraph compose["docker-compose"]
        FE["frontend<br/>React + Vite, served by nginx<br/>:5173"]

        subgraph sysA["agent-system-a"]
            API["FastAPI<br/>REST + SSE"]
            Graph["LangGraph supervisor<br/>+ specialists<br/>(input/output guardrails,<br/>iteration limits)"]
            SQLite[("SQLite checkpointer<br/>data/chat_history.sqlite")]
            API --- Graph
            Graph --- SQLite
        end

        subgraph sysB["agent-system-b"]
            A2A["A2A JSON-RPC<br/>:8002"]
            REST["REST API<br/>:8003"]
            ADK["Google ADK agent<br/>Component Manager"]
            A2A --- ADK
            REST --- ADK
        end

        MCP["mcp-server<br/>MCP over Streamable HTTP<br/>:8001<br/>(bearer token)"]
        VDB[("vector-db<br/>Qdrant<br/>:6333")]
    end

    subgraph ext["External services"]
        DigiKey["DigiKey Sandbox API<br/>(OAuth + ordering)"]
        LLMs["LLM providers<br/>Groq / Google / OpenRouter"]
    end

    User -->|"HTTPS"| FE
    FE -->|"POST /threads/.../messages/stream<br/>(SSE)"| API
    Graph -->|"A2A over the network<br/>(not a Python import)"| A2A
    API -->|"HTTP proxy<br/>(DigiKey OAuth)"| REST
    Graph -->|"MCP protocol"| MCP
    MCP --> VDB
    ADK -->|"OAuth + REST"| DigiKey
    Graph --> LLMs
    ADK --> LLMs

    classDef external fill:#f6f6f6,stroke:#999
    class DigiKey,LLMs,User external
```

## Notes

- **Network boundary, not a function call.** `agent-system-a` never imports
  `agent-system-b`'s Python package. All communication crosses the network:
  the core purchasing/inventory flow goes over A2A JSON-RPC (`:8002`); the
  DigiKey OAuth flow proxies over System B's own REST API (`:8003`).
- **Both systems expose SSE.** `agent-system-a`'s `/threads/{id}/messages/stream`
  streams LangGraph node-level progress (routing decisions, tool calls) as
  each specialist runs. `agent-system-b`'s own REST API independently streams
  token/tool events from its ADK agent.
- **Session state** lives in `agent-system-a`'s SQLite checkpointer
  (LangGraph `AsyncSqliteSaver`), keyed by `thread_id`, so conversation
  history and paused approvals survive across requests and restarts.
- **Guardrails** (NeMo Guardrails input/output rails) and **iteration
  limits** run as real graph nodes inside `agent-system-a`, not as
  middleware — see `langgraph_workflow.svg` for exactly where in the flow.
