"""Per-case token/cost tracking for the evaluation harness.

Nothing in the app tracks LLM usage today. This attaches a callback handler
to each case's `graph.ainvoke()` call (via the `callbacks=` parameter added
to `chat_service.send_message`/`resume_thread`) and reads LangChain's
standardized `AIMessage.usage_metadata`, which `ChatGroq` and
`ChatGoogleGenerativeAI` both populate.

Rates are `{"<model-name>": (dollars_per_million_input, dollars_per_million_output)}`,
keyed by the exact string each provider echoes back in `usage_metadata` /
`response_metadata["model_name"]` — verified against a live call per model
(each provider returns the same string passed to it in `app/config.py`, no
provider-side renaming). Standard on-demand rates, not batch pricing, since
the app calls `.ainvoke()` directly. Confirmed 2026-08-20:

- Groq (openai/gpt-oss-*, qwen/qwen3.6-27b): console.groq.com/docs/pricing
- Google (gemini-3.1-flash-lite): ai.google.dev/gemini-api/docs/pricing
- OpenRouter (nvidia/nemotron-3-ultra-550b-a55b, the fallback model): openrouter.ai

Any model missing from this table reports `cost_usd=None` instead of
silently costing $0 — re-verify and update rates here if pricing changes.
"""

from __future__ import annotations

from langchain_core.callbacks import AsyncCallbackHandler

MODEL_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-safeguard-20b": (0.075, 0.30),
    "qwen/qwen3.6-27b": (0.60, 3.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "nvidia/nemotron-3-ultra-550b-a55b": (0.50, 2.20),
}


class UsageCollector(AsyncCallbackHandler):
    """Accumulates per-call token usage for one case's graph invocation(s).

    `langgraph_node` is only available in callback `metadata` at *_start*
    time (`on_chat_model_start`) — LangChain's `on_llm_end` signature carries
    only `run_id`/`tags`, not `metadata`. So the node is captured on start
    and looked back up by `run_id` on end, the standard start/end
    correlation pattern for callback handlers.

    Every specialist (rag/wiring/coding/visualization) runs its LLM calls
    inside a prebuilt ReAct agent invoked as a plain nested `.ainvoke()`
    (app/graph.py `_run_agent`), so `langgraph_node` there is always that
    inner subgraph's own generic node name ("model") — not which specialist
    it belongs to. `_run_agent` tags that call with `metadata={"specialist":
    name}`, so we prefer that when present and fall back to `langgraph_node`
    for everything else (supervisor, guardrails).
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._node_by_run_id: dict[object, str | None] = {}

    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:  # noqa: ANN001
        run_id = kwargs.get("run_id")
        metadata = kwargs.get("metadata") or {}
        self._node_by_run_id[run_id] = metadata.get("specialist") or metadata.get("langgraph_node")

    async def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001 - LangChain LLMResult
        model_name = None
        if response.llm_output:
            model_name = response.llm_output.get("model_name") or response.llm_output.get("model")
        node = self._node_by_run_id.pop(kwargs.get("run_id"), None)

        for generation_list in response.generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if not usage:
                    continue
                self.calls.append(
                    {
                        "model": model_name
                        or (message.response_metadata or {}).get("model_name")
                        or (message.response_metadata or {}).get("model"),
                        "node": node,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }
                )

    def usage_summary(self) -> dict:
        """Total tokens/cost for the case, plus a per-node breakdown."""

        total_input = sum(call["input_tokens"] for call in self.calls)
        total_output = sum(call["output_tokens"] for call in self.calls)
        total_tokens = sum(call["total_tokens"] for call in self.calls)

        cost_usd = 0.0
        unpriced_models: set[str] = set()
        for call in self.calls:
            pricing = MODEL_PRICING.get(call["model"])
            if pricing is None:
                unpriced_models.add(call["model"] or "unknown")
                continue
            input_rate, output_rate = pricing
            cost_usd += call["input_tokens"] / 1_000_000 * input_rate
            cost_usd += call["output_tokens"] / 1_000_000 * output_rate

        by_node: dict[str, dict[str, int]] = {}
        for call in self.calls:
            node = call["node"] or "unknown"
            entry = by_node.setdefault(node, {"input_tokens": 0, "output_tokens": 0})
            entry["input_tokens"] += call["input_tokens"]
            entry["output_tokens"] += call["output_tokens"]

        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "cost_usd": None if unpriced_models else round(cost_usd, 6),
            "unpriced_models": sorted(unpriced_models),
            "tokens_by_node": by_node,
        }
