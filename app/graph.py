"""LangGraph supervisor and specialist workflow."""

import hashlib
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

from agents.coding_agent import build_agent as build_coder
from agents.rag_agent import build_agent as build_rag
from agents.robot_visualization_agent import build_agent as build_visual
from agents.wiring_agent import build_agent as build_wiring
from app.config import settings
from app.helpers import (
    extract_images,
    extract_result,
    merge_results,
    new_project,
    pin_map,
    project_context,
    to_text,
    wants_rewire,
)
from app.integrations.component_client import (
    contact_manager,
    last_argument,
    last_result,
)

VALID_ROUTES = {
    "rag_agent",
    "coding_agent",
    "wiring_agent",
    "robot_visualization_agent",
    "component_manager",
    "FINISH",
}
SAFE_FALLBACK_ROUTE = "FINISH"
MAX_ATTEMPTS_PER_AGENT = 2
# component_manager gets 3 attempts: propose + submit-after-approval
# is the normal two-call happy path, plus one retry of headroom. Note the
# propose -> approve -> submit hops are routed directly by
# purchase_approval_node, not through choose_route, so this cap only ever
# matters for supervisor-mediated re-routes to component_manager.
MAX_ATTEMPTS_BY_AGENT: dict[str, int] = {"component_manager": 3}
APPROVAL_REQUIRED_ROUTES = {"coding_agent", "robot_visualization_agent"}

AGENT_FACTORIES = {
    "rag_agent": build_rag,
    "coding_agent": build_coder,
    "wiring_agent": build_wiring,
    "robot_visualization_agent": build_visual,
}

SUPERVISOR_PROMPT = """Route specialist work. You may answer only brief conversational
messages that do not require a specialist, such as greetings, thanks, farewells, and
questions about what this robotics assistant can do. Do not answer unrelated general-
knowledge or out-of-scope questions.

Apply these rules in order and choose exactly one next_agent:
1. wiring_agent: the user asks to plan or allocate pins, wire components to a board,
   or avoid pin conflicts. Also route here first, before coding_agent or
   robot_visualization_agent, when the user names specific components to wire, code
   for, or model, and no wiring result for this request exists yet in completed_tasks.
2. component_manager: the user asks about component availability, price, or wants to
   buy, order, or purchase a part. Also route here to submit an already-approved
   purchase proposal when the task explicitly says a proposal was approved. Write
   the task as a plain instruction for a separate purchasing agent to act on
   directly (it has its own tools and makes its own decisions about which to call);
   do not try to decide which purchasing step to take yourself.
3. coding_agent: the user asks to write, fix, debug, explain, or validate code, or
   provides a code snippet. Arduino code still belongs here.
4. robot_visualization_agent: the user asks to create, show, render, preview, or model
   a robot in CAD, 3D, or OpenSCAD.
5. rag_agent: the user asks a factual question about Arduino or physical robotics
   hardware, such as a sensor's behavior, wiring, motor control, or documented specs.
- Follow-up confirmations: resolve short replies such as "yes", "proceed", "do that",
  or "the second one" from Recent conversation. If the previous Component Manager
  response offered to create a purchase proposal and the user accepts, route to
  component_manager and restate the accepted item, part number, and quantity in the
  task. This creates a proposal only; it never counts as approval to place an order.
  Actual order approval must come through the graph's purchase-approval interrupt.
- FINISH:
  a. Use it when every requested part already has a specialist result. Set task to a
     short completion note; the specialist results remain the final answer.
  b. For a greeting, thanks, farewell, or question about this assistant's capabilities,
     use FINISH and put a brief, friendly, user-facing reply in task. You may mention
     that the assistant helps with robotics hardware, wiring, Arduino code, component
     availability and purchasing, and robot visualization.
  c. For an unrelated or out-of-scope request, use FINISH and put a brief user-facing
     refusal in task that redirects the user to the supported robotics topics. Do not
     answer the unrelated question itself.

Before routing, inspect the latest result:
- If it answers the task and no requested part remains, choose FINISH.
- Retry the same specialist only if its result is incomplete or reports an error.
- Do not retry merely to improve wording.
- For multi-part requests, route the next unfinished part to the right specialist.

Set requires_multiple_agents to true only when two or more different specialists are
needed. Write a specific task; on retry, state exactly what must be corrected.
"""
SUPERVISOR_RESULT_LIMIT = 2_000


class ProjectPlan(TypedDict):
    """Engineering outputs shared by every specialist."""

    board: str | None
    components: list[dict[str, Any]]
    wiring: dict[str, Any] | None
    code_artifact: str | None
    model_artifact: str | None
    purchase: dict[str, Any] | None
    product_cards: list[dict[str, Any]]


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
    project: ProjectPlan
    pending_purchase_proposal: dict[str, Any] | None
    iteration_count: int
    multi_agent_request: bool | None
    input_blocked: bool
    final_answer: str | None


class RouteDecision(BaseModel):
    """Structured route returned by the supervisor."""

    next_agent: Literal[
        "rag_agent",
        "coding_agent",
        "wiring_agent",
        "robot_visualization_agent",
        "component_manager",
        "FINISH",
    ]
    task: str
    requires_multiple_agents: bool


def validate_route(route: str) -> str:
    """Use a safe fallback when the route is unknown."""

    if route in VALID_ROUTES:
        return route
    return SAFE_FALLBACK_ROUTE


def new_state(
    user_input: str,
    thread_id: str = "",
    project: dict[str, Any] | None = None,
) -> AgentState:
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
        "project": new_project(project),
        "pending_purchase_proposal": None,
        "iteration_count": 0,
        "multi_agent_request": None,
        "input_blocked": False,
        "final_answer": None,
    }


async def input_guard(state: AgentState) -> dict:
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


def route_input(state: AgentState) -> str:
    """Skip the agent workflow when the input guardrail blocks a request."""

    return "blocked" if state["input_blocked"] else "continue"


async def supervise(state: AgentState) -> dict:
    """Choose the next specialist without doing specialist work."""

    if state["iteration_count"] >= settings.max_agent_iterations:
        return {
            "next_agent": "FINISH",
            "final_answer": partial_answer(state),
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
    recent_conversation = []
    for message in state["messages"][-8:]:
        content = to_text(getattr(message, "content", None)).strip()
        if not content:
            continue
        speaker = getattr(message, "name", None) or getattr(message, "type", "message")
        recent_conversation.append({"speaker": speaker, "content": content[:1_000]})
    routing_context = (
        f"Original request: {state['original_query']}\n"
        f"Recent conversation: {recent_conversation}\n"
        f"Routes already used: {state['route_history']}\n"
        f"Completed tasks: {state['completed_tasks']}\n"
        f"Results so far: {compact_results}\n"
        f"Current project: {project_context(state['project'])}"
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

    update: dict[str, Any] = {
        "next_agent": route,
        "completed_tasks": state["completed_tasks"] + [task],
        "multi_agent_request": multi_agent_request,
    }
    # FINISH has no specialist node. For a conversational or unsupported request,
    # the supervisor's structured task is therefore the complete public response.
    # Never replace real specialist output when FINISH closes a completed workflow.
    if route == "FINISH" and not state["partial_results"]:
        update["final_answer"] = task.strip() or (
            "I can help with robotics hardware, wiring, Arduino code, component "
            "availability and purchasing, and robot visualization."
        )
    return update


def choose_route(state: AgentState) -> str:
    """Return only a validated graph edge."""

    route = validate_route(state["next_agent"])
    max_attempts = MAX_ATTEMPTS_BY_AGENT.get(route, MAX_ATTEMPTS_PER_AGENT)
    if state["route_history"].count(route) >= max_attempts:
        return "FINISH"
    return route


def route_agent(state: AgentState) -> str:
    """Pause before specialists that may write files or start a CAD render."""

    route = choose_route(state)
    if route in APPROVAL_REQUIRED_ROUTES:
        return "human_approval"
    return route


def approve_action(state: AgentState) -> dict:
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


def route_approval(state: AgentState) -> str:
    """Continue to the approved specialist, or finish after rejection."""

    return validate_route(state["next_agent"])


def route_purchase(state: AgentState) -> str:
    """Pause for approval when component_manager just created an unapproved proposal."""

    if state.get("pending_purchase_proposal"):
        return "purchase_approval"
    return "supervisor"


def approve_purchase(state: AgentState) -> dict:
    """Ask the caller to approve a purchase proposal's exact terms before it is submitted.

    Distinct from human_approval_node: that node gates an entire specialist
    run before it starts, using a generic {question, action, task, reason}
    payload. A purchase proposal already exists by the time this node runs,
    has richer immutable fields (price, total, expiry, ...), and on approval
    must route back into component_manager with the proposal's own
    approval_token and a fresh idempotency key rather than simply resuming.
    """

    proposal = state["pending_purchase_proposal"]
    response = interrupt(
        {
            "action": "place_order",
            "question": (
                f"Approve purchasing {proposal['quantity']}x "
                f"{proposal.get('component_name', proposal['component_id'])} for "
                f"{proposal['total']} {proposal['currency']}?"
            ),
            "proposal_id": proposal["proposal_id"],
            "component_id": proposal["component_id"],
            "component_name": proposal.get("component_name"),
            "quantity": proposal["quantity"],
            "supplier_name": proposal.get("supplier_name"),
            "unit_price": proposal["unit_price"],
            "currency": proposal["currency"],
            "fees": proposal.get("fees"),
            "total": proposal["total"],
            "delivery_estimate_days": proposal.get("delivery_estimate_days"),
            "expires_at": proposal["expires_at"],
        }
    )
    approved = response if isinstance(response, bool) else response.get("approved", False)
    if not approved:
        project = dict(state["project"])
        project["purchase"] = None
        return {
            "project": project,
            "pending_purchase_proposal": None,
            "next_agent": "FINISH",
            "final_answer": (
                f"Purchase cancelled; proposal {proposal['proposal_id']} was not submitted."
            ),
        }

    credential_id = response.get("payment_credential_id") if isinstance(response, dict) else None
    if not credential_id:
        return {
            "next_agent": "FINISH",
            "final_answer": (
                "Purchase was not submitted because no sandbox payment credential was provided."
            ),
        }

    from app.payment_vault import CredentialError, authorize

    try:
        credential = authorize(credential_id)
    except CredentialError as error:
        return {"next_agent": "FINISH", "final_answer": str(error)}

    idempotency_key = hashlib.sha256(
        f"{state['thread_id']}:{proposal['proposal_id']}".encode()
    ).hexdigest()
    task = (
        f"Submit approved proposal {proposal['proposal_id']} using approval_token "
        f"{proposal['approval_token']}, idempotency_key {idempotency_key}, and sandbox "
        f"payment_credential_id {credential_id} ({credential.brand} ending in "
        f"{credential.last4})."
    )
    return {
        "next_agent": "component_manager",
        "completed_tasks": state["completed_tasks"] + [task],
    }


async def run_agent(state: AgentState, name: str, factory: Callable[..., Awaitable[Any]]) -> dict:
    """Run one specialist and store its result."""

    wiring = state["project"]["wiring"]
    reset_wiring = name == "wiring_agent" and wants_rewire(state["original_query"])
    if name == "wiring_agent":
        existing = {} if reset_wiring else pin_map(wiring)
        agent = await factory(existing_assignments=existing)
    else:
        agent = await factory()

    task = state["completed_tasks"][-1]
    prompt = (
        f"Original request: {state['original_query']}\n"
        f"Your current task: {task}\n"
        f"Previous specialist results: {state['partial_results']}\n"
        f"Current project context: {project_context(state['project'])}"
    )
    if name in {"coding_agent", "robot_visualization_agent"} and wiring:
        prompt += f"\nConfirmed wiring plan to reuse exactly: {wiring}"
    elif name == "wiring_agent" and wiring and not reset_wiring:
        prompt += (
            "\nExisting wiring plan for this thread: "
            f"{wiring}\nThe allocator already protects these assignments internally. "
            "Add only the newly requested components."
        )
    elif reset_wiring:
        prompt += "\nThe user explicitly requested a redesign; saved pin assignments were cleared."

    result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})
    content = to_text(result["messages"][-1].content)

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
        image_paths.extend(extract_images(getattr(message, "content", None)))
        image_paths.extend(extract_images(getattr(message, "artifact", None)))
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

    partial_result = {"agent": name, "result": content}
    update: dict[str, Any] = {
        "messages": [AIMessage(content=content, name=name)],
        "route_history": state["route_history"] + [name],
        "partial_results": state["partial_results"] + [partial_result],
        "tool_trace": state["tool_trace"] + tool_trace,
        "image_paths": state["image_paths"] + list(dict.fromkeys(image_paths)),
        "iteration_count": state["iteration_count"] + 1,
    }
    project = dict(state["project"])
    if name == "wiring_agent":
        wiring_plan = extract_result(result["messages"], "format_wiring_plan")
        if wiring_plan is not None:
            project["board"] = wiring_plan.get("board")
            project["components"] = wiring_plan.get("components", [])
            project["wiring"] = wiring_plan
    elif name == "coding_agent":
        code_result = extract_result(result["messages"], "save_code")
        if code_result is not None:
            project["code_artifact"] = code_result.get("path")
    elif name == "robot_visualization_agent":
        model_result = extract_result(result["messages"], "render_openscad")
        if model_result is not None:
            project["model_artifact"] = model_result.get("preview_path")
    update["project"] = project
    return update


async def run_component(state: AgentState) -> dict:
    """Relay the supervisor's task to System B over A2A.

    Unlike the other specialists, this node has no model of its own:
    System B's ADK agent decides which read-only tools to call and with what
    arguments, and System A only reads the result. See
    app/integrations/component_client.py for why (avoids two models reasoning about the
    same purchase).
    """

    task = state["completed_tasks"][-1]
    result = await contact_manager(task)

    tool_trace: list[dict[str, Any]] = []
    if "error" in result:
        content = f"Component Manager error: {result['error']}"
    else:
        content = result.get("answer", "")
        for call in result.get("tool_calls", []):
            tool_trace.append(
                {
                    "agent": "component_manager",
                    "event": "call",
                    "tool": call.get("tool") or "unknown",
                    "arguments": call.get("arguments", {}),
                    "tool_call_id": call.get("id"),
                }
            )
        for entry in result.get("tool_results", []):
            tool_trace.append(
                {
                    "agent": "component_manager",
                    "event": "result",
                    "tool": entry.get("tool") or "unknown",
                    "content": str(entry.get("result"))[:4_000],
                    "tool_call_id": entry.get("id"),
                }
            )

    partial_result = {"agent": "component_manager", "result": content}
    update: dict[str, Any] = {
        "messages": [AIMessage(content=content, name="component_manager")],
        "route_history": state["route_history"] + ["component_manager"],
        "partial_results": state["partial_results"] + [partial_result],
        "tool_trace": state["tool_trace"] + tool_trace,
        "iteration_count": state["iteration_count"] + 1,
    }
    project = dict(state["project"])

    if "error" not in result:
        search_result = last_result(result, "search_digikey")
        if search_result is not None and search_result.get("success"):
            project["product_cards"] = search_result.get("offers", [])

        order_result = last_result(result, "place_digikey_order")
        if order_result is not None and order_result.get("success"):
            update["pending_purchase_proposal"] = None
            project["purchase"] = {
                "proposal_id": last_argument(result, "place_digikey_order", "proposal_id"),
                "order_id": order_result.get("order_id"),
                "status": order_result.get("status"),
            }
        else:
            proposal_result = last_result(result, "create_digikey_proposal")
            if proposal_result is not None and proposal_result.get("success"):
                update["pending_purchase_proposal"] = proposal_result
                project["purchase"] = {"proposal": proposal_result}

    update["project"] = project

    return update


def finalize(state: AgentState) -> dict:
    """Combine specialist results without inventing new information."""

    if state.get("final_answer"):
        return {}

    if not state["partial_results"]:
        return {"final_answer": "No specialist produced a result."}

    return {"final_answer": merge_results(state["partial_results"])}


def partial_answer(state: AgentState) -> str:
    """Return completed work when the iteration cap is reached."""

    if not state["partial_results"]:
        return "The iteration limit was reached before any specialist completed work."

    results = merge_results(state["partial_results"])
    return f"Iteration limit reached. Partial results:\n\n{results}"


def build_graph(checkpointer=None):
    """Build and compile the complete multi-agent graph."""

    graph = StateGraph(AgentState)

    graph.add_node("input_guardrail", input_guard)
    graph.add_node("supervisor", supervise)
    graph.add_node("human_approval", approve_action)
    graph.add_node("component_manager", run_component)
    graph.add_node("purchase_approval_node", approve_purchase)
    graph.add_node("finalizer", finalize)

    for name, factory in AGENT_FACTORIES.items():
        graph.add_node(name, partial(run_agent, name=name, factory=factory))
        graph.add_edge(name, "supervisor")

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        route_input,
        {"blocked": END, "continue": "supervisor"},
    )
    graph.add_conditional_edges(
        "supervisor",
        route_agent,
        {
            **{name: name for name in AGENT_FACTORIES},
            "component_manager": "component_manager",
            "human_approval": "human_approval",
            "FINISH": "finalizer",
        },
    )
    graph.add_conditional_edges(
        "human_approval",
        route_approval,
        {
            "coding_agent": "coding_agent",
            "robot_visualization_agent": "robot_visualization_agent",
            "FINISH": "finalizer",
        },
    )
    graph.add_conditional_edges(
        "component_manager",
        route_purchase,
        {"purchase_approval": "purchase_approval_node", "supervisor": "supervisor"},
    )
    graph.add_conditional_edges(
        "purchase_approval_node",
        route_approval,
        {"component_manager": "component_manager", "FINISH": "finalizer"},
    )
    graph.add_edge("finalizer", END)

    return graph.compile(checkpointer=checkpointer, name="robotics_multi_agent")
