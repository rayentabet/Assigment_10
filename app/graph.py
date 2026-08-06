"""LangGraph supervisor and specialist workflow."""

import ast
import json
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel

from agents.coding_agent import create_coding_agent
from agents.general_agent import create_general_agent
from agents.rag_agent import create_rag_agent
from agents.robot_visualization_agent import create_robot_visualization_agent
from app.config import settings

VALID_ROUTES = {
    "rag_agent",
    "coding_agent",
    "robot_visualization_agent",
    "general_agent",
    "FINISH",
}
SAFE_FALLBACK_ROUTE = "general_agent"
MAX_ATTEMPTS_PER_AGENT = 2
MAX_ATTEMPTS_BY_AGENT = {"general_agent": 1}
APPROVAL_REQUIRED_ROUTES = {"coding_agent", "robot_visualization_agent"}

AGENT_FACTORIES = {
    "rag_agent": create_rag_agent,
    "coding_agent": create_coding_agent,
    "robot_visualization_agent": create_robot_visualization_agent,
    "general_agent": create_general_agent,
}

SUPERVISOR_PROMPT = """Route the request; do not answer it yourself.

Apply these rules in order and choose exactly one next_agent:
1. coding_agent: the user asks to write, fix, debug, explain, or validate code, or
   provides a code snippet. Arduino code still belongs here.
2. robot_visualization_agent: the user asks to create, show, render, preview, or model
   a robot in CAD, 3D, or OpenSCAD.
3. rag_agent: the user asks a factual question about Arduino or physical robotics
   hardware, such as a sensor's behavior, wiring, motor control, or documented specs.
4. general_agent: general knowledge, conceptual programming questions without code,
   and anything unrelated to Arduino or robotics hardware.
- FINISH: use only when every requested part already has a specialist result.

Before routing, inspect the latest result:
- If it answers the task and no requested part remains, choose FINISH.
- Retry the same specialist only if its result is incomplete or reports an error.
- Do not retry merely to improve wording.
- For multi-part requests, route the next unfinished part to the right specialist.

Set requires_multiple_agents to true only when two or more different specialists are
needed. Write a specific task; on retry, state exactly what must be corrected.
"""
SUPERVISOR_RESULT_LIMIT = 2_000


class AgentState(TypedDict):
    """Information shared by all graph nodes."""

    thread_id: str
    messages: Annotated[list, add_messages]
    original_query: str
    next_agent: str
    route_history: list[str]
    completed_tasks: list[str]
    partial_results: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    image_paths: list[str]
    iteration_count: int
    multi_agent_request: bool | None
    input_blocked: bool
    raw_answer: str | None
    final_answer: str | None


class RouteDecision(BaseModel):
    """Structured route returned by the supervisor."""

    next_agent: Literal[
        "rag_agent",
        "coding_agent",
        "robot_visualization_agent",
        "general_agent",
        "FINISH",
    ]
    task: str
    requires_multiple_agents: bool


def validate_route(route: str) -> str:
    """Use a safe fallback when the route is unknown."""

    if route in VALID_ROUTES:
        return route
    return SAFE_FALLBACK_ROUTE


def new_state(user_input: str, thread_id: str = "") -> AgentState:
    """Create the initial graph state for one request."""

    return {
        "thread_id": thread_id,
        "messages": [HumanMessage(content=user_input)],
        "original_query": user_input,
        "next_agent": "",
        "route_history": [],
        "completed_tasks": [],
        "partial_results": [],
        "tool_trace": [],
        "image_paths": [],
        "iteration_count": 0,
        "multi_agent_request": None,
        "input_blocked": False,
        "raw_answer": None,
        "final_answer": None,
    }


async def input_guardrail_node(state: AgentState) -> dict:
    """Mask sensitive input and stop unsafe requests before routing."""

    from app.guardrails import BLOCKED_MESSAGE, check_input

    safe_input = await check_input(state["original_query"])
    if safe_input is None:
        return {
            "input_blocked": True,
            "next_agent": "FINISH",
            "final_answer": BLOCKED_MESSAGE,
        }
    return {"original_query": safe_input}


def route_after_input_guardrail(state: AgentState) -> str:
    """Skip the agent workflow when the input guardrail blocks a request."""

    return "blocked" if state["input_blocked"] else "continue"


async def supervisor_node(state: AgentState) -> dict:
    """Choose the next specialist without doing specialist work."""

    if state["iteration_count"] >= settings.max_agent_iterations:
        return {
            "next_agent": "FINISH",
            "final_answer": make_partial_answer(state),
        }

    model = ChatGroq(model=settings.supervisor_model, temperature=0)
    router = model.with_structured_output(
        RouteDecision,
        method="json_schema",
        strict=True,
    )

    compact_results = [
        {
            "agent": item["agent"],
            "result": item["result"][:SUPERVISOR_RESULT_LIMIT],
        }
        for item in state["partial_results"]
    ]
    routing_context = (
        f"Original request: {state['original_query']}\n"
        f"Routes already used: {state['route_history']}\n"
        f"Completed tasks: {state['completed_tasks']}\n"
        f"Results so far: {compact_results}"
    )

    decision = await router.ainvoke(
        [
            SystemMessage(content=SUPERVISOR_PROMPT),
            HumanMessage(content=routing_context),
        ]
    )
    route = validate_route(decision.next_agent)
    task = decision.task

    multi_agent_request = state["multi_agent_request"]
    if multi_agent_request is None:
        multi_agent_request = decision.requires_multiple_agents

    return {
        "next_agent": route,
        "completed_tasks": state["completed_tasks"] + [task],
        "multi_agent_request": multi_agent_request,
    }


def choose_route(state: AgentState) -> str:
    """Return only a validated graph edge."""

    route = validate_route(state["next_agent"])
    max_attempts = MAX_ATTEMPTS_BY_AGENT.get(route, MAX_ATTEMPTS_PER_AGENT)
    if state["route_history"].count(route) >= max_attempts:
        return "FINISH"
    return route


def route_with_approval(state: AgentState) -> str:
    """Pause before specialists that may write files or start a CAD render."""

    route = choose_route(state)
    if route in APPROVAL_REQUIRED_ROUTES:
        return "human_approval"
    return route


def human_approval_node(state: AgentState) -> dict:
    """Ask the caller to approve the pending side effect before it happens."""

    route = validate_route(state["next_agent"])
    task = state["completed_tasks"][-1]
    response = interrupt(
        {
            "question": f"Approve running {route}?",
            "action": route,
            "task": task,
            "reason": "This specialist may write generated files or run an expensive render.",
        }
    )
    approved = response if isinstance(response, bool) else response.get("approved", False)
    if approved:
        return {}
    return {
        "next_agent": "FINISH",
        "final_answer": f"Cancelled before running {route}; no specialist action was taken.",
    }


def route_after_human_approval(state: AgentState) -> str:
    """Continue to the approved specialist, or finish after rejection."""

    return validate_route(state["next_agent"])


async def run_specialist(
    state: AgentState, name: str, factory: Callable[[], Awaitable[Any]]
) -> dict:
    """Run one specialist and store its result."""

    agent = await factory()

    task = state["completed_tasks"][-1]
    prompt = (
        f"Original request: {state['original_query']}\n"
        f"Your current task: {task}\n"
        f"Previous specialist results: {state['partial_results']}"
    )

    result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})
    content = result["messages"][-1].content

    tool_trace = []
    image_paths = []
    for message in result["messages"]:
        for tool_call in getattr(message, "tool_calls", []):
            arguments = tool_call.get("args", {})
            tool_trace.append(
                {
                    "agent": name,
                    "event": "call",
                    "tool": tool_call.get("name", "unknown"),
                    "arguments": arguments,
                    "tool_call_id": tool_call.get("id"),
                }
            )
            if tool_call.get("name") == "show_image" and arguments.get("image_path"):
                image_path = Path(str(arguments["image_path"]))
                if not image_path.is_absolute():
                    image_path = settings.rag_project_path / image_path
                image_paths.append(str(image_path.resolve()))
        image_paths.extend(_extract_image_paths(getattr(message, "content", None)))
        image_paths.extend(_extract_image_paths(getattr(message, "artifact", None)))
        if message.type == "tool":
            message_content = message.content
            if isinstance(message_content, list) and any(
                isinstance(block, dict) and block.get("type") == "image"
                for block in message_content
            ):
                recorded_content = "[image returned]"
            else:
                recorded_content = str(message_content)[:4_000]
            tool_trace.append(
                {
                    "agent": name,
                    "event": "result",
                    "tool": getattr(message, "name", None) or "unknown",
                    "content": recorded_content,
                    "tool_call_id": getattr(message, "tool_call_id", None),
                }
            )

    partial_result = {"agent": name, "result": str(content)}
    return {
        "messages": [AIMessage(content=str(content), name=name)],
        "route_history": state["route_history"] + [name],
        "partial_results": state["partial_results"] + [partial_result],
        "tool_trace": state["tool_trace"] + tool_trace,
        "image_paths": state["image_paths"] + list(dict.fromkeys(image_paths)),
        "iteration_count": state["iteration_count"] + 1,
    }


def format_results(results: list[dict[str, Any]]) -> str:
    """Combine final specialist answers without exposing routing metadata."""

    return "\n\n".join(item["result"] for item in results)


def _extract_image_paths(value: Any) -> list[str]:
    """Find image and preview paths in structured tool results."""

    if isinstance(value, dict):
        paths = []
        for key, item in value.items():
            if key in {"image_path", "preview_path"} and item:
                path = Path(str(item))
                if not path.is_absolute():
                    path = settings.rag_project_path / path
                paths.append(str(path.resolve()))
            else:
                paths.extend(_extract_image_paths(item))
        return paths
    if isinstance(value, list):
        return [path for item in value for path in _extract_image_paths(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
        if parsed == value:
            return []
        return _extract_image_paths(parsed)
    return []


def finalizer_node(state: AgentState) -> dict:
    """Combine specialist results without inventing new information."""

    if state.get("final_answer"):
        return {}

    if not state["partial_results"]:
        return {"final_answer": "No specialist produced a result."}

    return {"final_answer": format_results(state["partial_results"])}


async def output_guardrail_node(state: AgentState) -> dict:
    """Mask or block the completed answer before returning it."""

    from app.guardrails import BLOCKED_MESSAGE, check_output

    answer = state["final_answer"] or ""
    safe_output = await check_output(state["original_query"], answer, evidence=[])
    return {
        "raw_answer": answer,
        "final_answer": safe_output if safe_output is not None else BLOCKED_MESSAGE,
    }


def make_partial_answer(state: AgentState) -> str:
    """Return completed work when the iteration cap is reached."""

    if not state["partial_results"]:
        return "The iteration limit was reached before any specialist completed work."

    results = format_results(state["partial_results"])
    return f"Iteration limit reached. Partial results:\n\n{results}"


def build_graph(checkpointer=None):
    """Build and compile the complete multi-agent graph."""

    graph = StateGraph(AgentState)

    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("finalizer", finalizer_node)
    graph.add_node("output_guardrail", output_guardrail_node)

    for name, factory in AGENT_FACTORIES.items():
        graph.add_node(name, partial(run_specialist, name=name, factory=factory))
        graph.add_edge(name, "supervisor")

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        route_after_input_guardrail,
        {"blocked": END, "continue": "supervisor"},
    )
    graph.add_conditional_edges(
        "supervisor",
        route_with_approval,
        {
            **{name: name for name in AGENT_FACTORIES},
            "human_approval": "human_approval",
            "FINISH": "finalizer",
        },
    )
    graph.add_conditional_edges(
        "human_approval",
        route_after_human_approval,
        {
            "coding_agent": "coding_agent",
            "robot_visualization_agent": "robot_visualization_agent",
            "FINISH": "finalizer",
        },
    )
    graph.add_edge("finalizer", "output_guardrail")
    graph.add_edge("output_guardrail", END)

    return graph.compile(checkpointer=checkpointer, name="robotics_multi_agent")
