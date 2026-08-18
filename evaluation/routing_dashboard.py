"""Streamlit dashboard for interactively testing supervisor routing.

Distinct from dashboard.py (which reviews saved evaluation runs): this one
drives the live graph directly, for fast iteration while tuning
SUPERVISOR_PROMPT or adding specialists — type a query, see exactly which
agents ran, with no evaluation file to write first. Also batch-runs the
routing-relevant cases from evaluation/golden_dataset/v2/cases.jsonl.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    # Run standalone with `streamlit run evaluation/routing_dashboard.py` (no
    # PYTHONPATH=. needed, unlike run_evaluation.py) — the repo root isn't on
    # sys.path by default, so the app.* imports below would otherwise fail.
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from app.chat_service import initialize, resume_thread, send_message
from app.graph import AGENT_FACTORIES, VALID_ROUTES

GOLDEN_DATASET = HERE / "golden_dataset" / "v2" / "cases.jsonl"

st.set_page_config(page_title="Routing Test Dashboard", page_icon="🧭", layout="wide")
st.title("Agent Routing Test Dashboard")
st.caption(
    "Drives the live supervisor directly — no evaluation file needed. "
    "For reviewing saved runs, use evaluation/dashboard.py instead."
)


@st.cache_resource
def get_loop() -> asyncio.AbstractEventLoop:
    """One persistent event loop per Streamlit server process.

    chat_service.py keeps module-level singletons (the SQLite connection, the
    compiled graph) bound to whichever event loop first initialized them.
    Streamlit reruns the script on every interaction, so a fresh
    asyncio.run() per click would create a new loop each time and break those
    singletons; reusing one cached loop keeps them valid across reruns.
    """

    return asyncio.new_event_loop()


def run_async(coro):
    return get_loop().run_until_complete(coro)


run_async(initialize())


def route_chain(route_history: list[str]) -> str:
    return " → ".join(route_history) if route_history else "(none — FINISH immediately)"


async def run_query(
    query: str | None,
    turns: list[dict] | None,
    auto_approve: bool,
    thread_id: str | None = None,
) -> dict:
    """Run one query, or a scripted list of turns, on a fresh or given thread."""

    thread_id = thread_id or f"routing-dashboard-{uuid.uuid4()}"

    if turns:
        result: dict = {}
        for turn in turns:
            if "query" in turn:
                result = await send_message(turn["query"], thread_id=thread_id)
            elif "resume" in turn:
                result = await resume_thread(thread_id, turn["resume"]["approved"])
            if result.get("__interrupt__") and turn is turns[-1] and auto_approve:
                result = await resume_thread(thread_id, True)
        return result

    result = await send_message(query, thread_id=thread_id)
    while result.get("__interrupt__") and auto_approve:
        result = await resume_thread(thread_id, True)
    return result


def load_cases() -> list[dict]:
    if not GOLDEN_DATASET.exists():
        return []
    return [json.loads(line) for line in GOLDEN_DATASET.read_text().splitlines() if line.strip()]


with st.sidebar:
    st.subheader("Current routes")
    st.code("\n".join(sorted(VALID_ROUTES)), language=None)
    st.caption(f"{len(AGENT_FACTORIES)} LLM specialists + component_manager (relay, no model) + FINISH")

single_tab, batch_tab = st.tabs(["Ad-hoc query", "Batch: golden dataset"])

with single_tab:
    st.subheader("Send one query")
    query = st.text_area("Query", placeholder="Wire an HC-SR04 ultrasonic sensor to an Arduino Uno.")
    auto_approve = st.checkbox(
        "Auto-approve any pending action",
        value=True,
        help=(
            "coding_agent, robot_visualization_agent, and purchase proposals pause for "
            "approval. On: automatically approve so you see the full route in one click. "
            "Off: stop at the pause so you can inspect the approval payload."
        ),
    )
    expected_routes_raw = st.text_input(
        "Expected routes (optional, comma-separated)", placeholder="wiring_agent, coding_agent"
    )

    if st.button("Test routing", type="primary", disabled=not query.strip()):
        with st.spinner("Running the supervisor..."):
            result = run_async(run_query(query.strip(), None, auto_approve))
        st.session_state["last_result"] = result
        st.session_state["last_thread_id"] = result.get("thread_id")

    result = st.session_state.get("last_result")
    if result:
        route_history = result.get("route_history", [])
        st.markdown(f"**Route:** {route_chain(route_history)}")

        if expected_routes_raw.strip():
            expected = [r.strip() for r in expected_routes_raw.split(",") if r.strip()]
            if expected == route_history:
                st.success(f"Matches expected: {' → '.join(expected)}")
            else:
                st.error(f"Expected {' → '.join(expected) or '(none)'}, got {route_chain(route_history)}")

        cols = st.columns(3)
        cols[0].metric("Iterations", result.get("iteration_count", 0))
        cols[1].metric("Specialists run", len(route_history))
        cols[2].metric(
            "Status", "Paused for approval" if result.get("__interrupt__") else "Completed"
        )

        if result.get("__interrupt__"):
            payload = getattr(result["__interrupt__"][0], "value", result["__interrupt__"][0])
            st.warning("Paused for approval — auto-approve was off.")
            st.json(payload)
            approve_col, reject_col = st.columns(2)
            if approve_col.button("Approve and continue"):
                with st.spinner("Resuming..."):
                    resumed = run_async(
                        resume_thread(st.session_state["last_thread_id"], True)
                    )
                st.session_state["last_result"] = resumed
                st.rerun()
            if reject_col.button("Reject and continue"):
                with st.spinner("Resuming..."):
                    resumed = run_async(
                        resume_thread(st.session_state["last_thread_id"], False)
                    )
                st.session_state["last_result"] = resumed
                st.rerun()

        with st.expander("Per-step tasks (what the supervisor asked each specialist to do)"):
            for i, task in enumerate(result.get("completed_tasks", [])):
                st.text(f"{i + 1}. {task}")

        with st.expander("Tool trace"):
            tool_trace = result.get("tool_trace", [])
            st.json(tool_trace) if tool_trace else st.caption("No tool calls recorded.")

        if result.get("final_answer"):
            st.subheader("Final answer")
            st.write(result["final_answer"])

with batch_tab:
    st.subheader("Run cases from the golden dataset")
    cases = load_cases()
    if not cases:
        st.info(f"No cases found at {GOLDEN_DATASET}.")
    else:
        categories = sorted({c["category"] for c in cases})
        selected_categories = st.multiselect(
            "Categories", categories, default=[c for c in ("routing", "guardrail") if c in categories]
        )
        skip_output_only = st.checkbox(
            "Skip output-only guardrail cases (they test check_output() directly, not routing)",
            value=True,
        )
        skip_simulated = st.checkbox(
            "Skip cases needing simulated failures (not supported by this dashboard)", value=True
        )

        runnable = [
            c
            for c in cases
            if c["category"] in selected_categories
            and not (skip_output_only and c.get("mode") == "output_only")
            and not (skip_simulated and "simulate" in c)
        ]
        st.caption(f"{len(runnable)} of {len(cases)} cases match the current filters.")

        if st.button("Run selected cases", type="primary", disabled=not runnable):
            progress = st.progress(0.0, text="Starting...")
            results = []
            for i, case in enumerate(runnable):
                progress.progress((i + 1) / len(runnable), text=f"Running {case['id']}...")
                try:
                    outcome = run_async(
                        run_query(case.get("query"), case.get("turns"), auto_approve=True)
                    )
                    actual_routes = outcome.get("route_history", [])
                    expected_routes = case.get("expected", {}).get("routes")
                    if expected_routes is None:
                        verdict = "n/a"
                    elif expected_routes == actual_routes:
                        verdict = "pass"
                    else:
                        verdict = "fail"
                    results.append(
                        {
                            "id": case["id"],
                            "category": case["category"],
                            "expected_routes": " → ".join(expected_routes)
                            if expected_routes is not None
                            else "(not asserted)",
                            "actual_routes": route_chain(actual_routes),
                            "verdict": verdict,
                        }
                    )
                except Exception as error:  # noqa: BLE001 - surface any case's failure, keep going
                    results.append(
                        {
                            "id": case["id"],
                            "category": case["category"],
                            "expected_routes": "(error)",
                            "actual_routes": f"{type(error).__name__}: {error}",
                            "verdict": "error",
                        }
                    )
            progress.empty()
            st.session_state["batch_results"] = results

        batch_results = st.session_state.get("batch_results")
        if batch_results:
            passed = sum(1 for r in batch_results if r["verdict"] == "pass")
            asserted = sum(1 for r in batch_results if r["verdict"] in ("pass", "fail"))
            metric_cols = st.columns(3)
            metric_cols[0].metric("Routing matches", f"{passed}/{asserted or 1}")
            metric_cols[1].metric("Errors", sum(1 for r in batch_results if r["verdict"] == "error"))
            metric_cols[2].metric("No route assertion", sum(1 for r in batch_results if r["verdict"] == "n/a"))
            st.dataframe(batch_results, width="stretch", hide_index=True)
