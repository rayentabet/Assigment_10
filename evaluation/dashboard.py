"""Streamlit dashboard for multi-agent evaluation history."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

HERE = Path(__file__).parent
PROJECT_DIRECTORY = HERE.parent
RUNS_DIRECTORY = HERE / "runs"
RUNNER = HERE / "run_evaluation.py"

st.set_page_config(page_title="Multi-Agent Evaluation", layout="wide")
st.title("Multi-Agent Evaluation Dashboard")

with st.sidebar:
    st.header("Run evaluation")
    run_name = st.text_input("Run name", "routing_guardrails")
    if st.button("Run all 10 cases", type="primary"):
        with st.spinner("Running routing, agents, and guardrails..."):
            process = subprocess.run(
                [sys.executable, str(RUNNER), "--run-name", run_name],
                cwd=PROJECT_DIRECTORY,
                env={**os.environ, "PYTHONPATH": str(PROJECT_DIRECTORY)},
                capture_output=True,
                text=True,
            )
        if process.returncode == 0:
            st.success("Evaluation completed.")
            st.code(process.stdout)
            st.rerun()
        else:
            st.error("Evaluation failed.")
            st.code(process.stderr or process.stdout)

run_directories = sorted(
    (path for path in RUNS_DIRECTORY.glob("*") if path.is_dir()), reverse=True
) if RUNS_DIRECTORY.exists() else []
legacy_results = HERE / "results.csv"
if legacy_results.exists():
    run_directories.append(HERE)

if not run_directories:
    st.info("No saved runs yet. Start one from the sidebar.")
    st.stop()

selected_directory = st.selectbox(
    "Saved run",
    run_directories,
    format_func=lambda path: "Latest legacy result" if path == HERE else path.name,
)

metadata_path = selected_directory / "metadata.json"
results_path = selected_directory / "results.csv"
metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
results = pd.read_csv(results_path) if results_path.exists() else pd.DataFrame()

if results.empty:
    st.warning("This run has no saved case results yet.")
    st.json(metadata)
    st.stop()

results["answer_correct"] = (
    results["answer_correct"].astype(str).str.lower() == "true"
)
route_correct = results["expected_route"] == results["actual_route"]
guardrail_correct = results["expected_guardrail"] == results["actual_guardrail"]
error_count = (results["actual_route"] == "error").sum()

metrics = st.columns(5)
metrics[0].metric("Score", f"{results['answer_correct'].sum()}/{len(results)}")
metrics[1].metric("Pass rate", f"{results['answer_correct'].mean():.0%}")
metrics[2].metric("Route accuracy", f"{route_correct.mean():.0%}")
metrics[3].metric("Guardrail accuracy", f"{guardrail_correct.mean():.0%}")
metrics[4].metric("Errors", int(error_count))

st.caption(
    f"Status: {metadata.get('status', 'unknown')} · "
    f"Started: {metadata.get('started_at', 'unknown')}"
)

summary_tab, cases_tab, details_tab = st.tabs(["Summary", "Cases", "Inspect result"])

with summary_tab:
    st.subheader("Results by category")
    category_scores = (
        results.groupby("category")["answer_correct"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "passed", "count": "total"})
    )
    category_scores["pass_rate"] = category_scores["passed"] / category_scores["total"]
    st.dataframe(category_scores, width="stretch")
    st.bar_chart(category_scores["pass_rate"])

    st.subheader("Models")
    st.json(metadata.get("models", {}))

with cases_tab:
    status_filter = st.selectbox("Status", ["All", "Passed", "Failed"])
    visible = results
    if status_filter == "Passed":
        visible = results[results["answer_correct"]]
    elif status_filter == "Failed":
        visible = results[~results["answer_correct"]]

    case_columns = [
        "id",
        "category",
        "expected_route",
        "actual_route",
    ]
    if "iteration_count" in visible.columns:
        case_columns.append("iteration_count")
    case_columns += [
        "expected_guardrail",
        "actual_guardrail",
        "answer_correct",
        "what_went_wrong",
    ]
    st.dataframe(
        visible[case_columns],
        width="stretch",
        hide_index=True,
    )

with details_tab:
    selected_id = st.selectbox("Case", results["id"].tolist())
    result = results[results["id"] == selected_id].iloc[0]
    st.markdown(f"**Question:** {result['query']}")
    left, right = st.columns(2)
    left.markdown(f"**Expected route:** {result['expected_route']}")
    left.markdown(f"**Expected guardrail:** {result['expected_guardrail']}")
    right.markdown(f"**Actual route:** {result['actual_route']}")
    right.markdown(
        f"**Iterations:** {int(result['iteration_count'])}"
        if "iteration_count" in results.columns
        else "**Iterations:** not recorded in this older run"
    )
    right.markdown(f"**Actual guardrail:** {result['actual_guardrail']}")

    if result["answer_correct"]:
        st.success("Passed")
    else:
        st.error(result["what_went_wrong"] or "Failed")

    st.subheader("Full answer")
    st.write(result["answer"] if pd.notna(result["answer"]) else "No answer recorded.")

    raw_answer = result.get("raw_answer")
    if pd.notna(raw_answer) and raw_answer != result["answer"]:
        with st.expander("Raw answer before output guardrails"):
            st.write(raw_answer)

    st.subheader("Tool calls")
    raw_tool_calls = result.get("tool_calls", "[]")
    try:
        tool_calls = json.loads(raw_tool_calls) if pd.notna(raw_tool_calls) else []
    except (TypeError, json.JSONDecodeError):
        tool_calls = []
    if tool_calls:
        st.json(tool_calls)
    else:
        st.caption("No tool calls were recorded for this case.")

    raw_image_paths = result.get("image_paths", "[]")
    try:
        image_paths = json.loads(raw_image_paths) if pd.notna(raw_image_paths) else []
    except (TypeError, json.JSONDecodeError):
        image_paths = []
    if image_paths:
        st.subheader("Retrieved images")
        for image_path in image_paths:
            path = Path(image_path)
            if path.is_file():
                st.image(str(path), caption=path.name)
            else:
                st.warning(f"Retrieved image not found: {image_path}")
