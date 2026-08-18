"""Streamlit dashboard for saved evaluation runs.

Two evaluation families, one dashboard:

- **Agent Evaluation (System A)** — saved runs from `run_evaluation.py`:
  routing, tool selection/arguments/order, approvals, guardrails.
- **RAG Retrieval Evaluation** — saved RAGAS runs from the sibling
  Assignment_8 project (read-only: this tab only reads its output files,
  it doesn't run RAGAS itself).

Distinct from `routing_dashboard.py`, which drives the live graph directly
for fast iteration while tuning prompts — this dashboard only reviews saved
run artifacts on disk.
"""

import argparse
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

if str(PROJECT_DIRECTORY) not in sys.path:
    # `streamlit run evaluation/dashboard.py` doesn't put the repo root on
    # sys.path the way `PYTHONPATH=. python -m ...` does.
    sys.path.insert(0, str(PROJECT_DIRECTORY))

from app.config import settings  # noqa: E402
from evaluation.comparators import aggregate_summary  # noqa: E402
from evaluation.run_evaluation import DATASET, load_cases, select_cases  # noqa: E402

RAG_RUNS_DIRECTORY = Path(settings.rag_project_path) / "runs"

METRIC_LABELS = {
    "case_pass": "Case pass rate",
    "route_correct": "Exact routing accuracy",
    "tool_selection_correct": "Tool-selection accuracy",
    "tool_arguments_correct": "Tool-argument accuracy",
    "tool_order_correct": "Tool-order accuracy",
    "guardrail_correct": "Guardrail accuracy",
    "approval_correct": "Approval correctness",
}

ASSERTION_LABELS = {
    "route_correct": "Routing",
    "tool_selection_correct": "Tool selection",
    "tool_arguments_correct": "Tool arguments",
    "tool_order_correct": "Tool order",
    "guardrail_correct": "Guardrail",
    "approval_correct": "Approval",
    "final_correct": "Final answer",
    "project_correct": "Project state",
    "cross_check_correct": "Cross-check",
    "recovery_correct": "Recovery",
}

RAG_METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


# =============================================================================
# Agent evaluation: data loading
# =============================================================================


def list_run_directories() -> list[Path]:
    if not RUNS_DIRECTORY.exists():
        return []
    return sorted((path for path in RUNS_DIRECTORY.glob("*") if path.is_dir()), reverse=True)


def load_run(directory: Path) -> dict:
    """Load one saved run. `schema` is "v2" (case_results.jsonl), "legacy"
    (results.csv only, predates route/tool/approval granularity), or "empty".
    """

    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}

    jsonl_path = directory / "case_results.jsonl"
    if jsonl_path.exists():
        cases = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
        if cases:
            return {"metadata": metadata, "cases": cases, "schema": "v2"}

    csv_path = directory / "results.csv"
    if csv_path.exists():
        legacy_df = pd.read_csv(csv_path)
        if not legacy_df.empty:
            return {"metadata": metadata, "cases": None, "legacy_df": legacy_df, "schema": "legacy"}

    return {"metadata": metadata, "cases": [], "schema": "empty"}


# =============================================================================
# Agent evaluation: shared grouping helper (reused by specialist / single-vs-multi)
# =============================================================================


def breakdown_by(cases: list[dict], label_fn) -> pd.DataFrame:
    """Group cases by label_fn and re-run aggregate_summary per group."""

    groups: dict[str, list[dict]] = {}
    for case in cases:
        groups.setdefault(label_fn(case), []).append(case)
    rows = []
    for label, subset in groups.items():
        summary = aggregate_summary(subset)
        rows.append(
            {
                "group": label,
                "cases": len(subset),
                "case_pass_rate": summary["metrics"]["case_pass"]["rate"],
                "route_accuracy": summary["metrics"]["route_correct"]["rate"],
                "tool_selection_accuracy": summary["metrics"]["tool_selection_correct"]["rate"],
                "tool_argument_accuracy": summary["metrics"]["tool_arguments_correct"]["rate"],
            }
        )
    return pd.DataFrame(rows).sort_values("group").reset_index(drop=True)


def agent_count_label(case: dict) -> str:
    count = len(case.get("expected_routes", []))
    if count == 0:
        return "no-agent (FINISH)"
    if count == 1:
        return "single-agent"
    return "multi-agent"


def verdict_icon(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "✅" if value else "❌"


# =============================================================================
# Agent evaluation: section renderers
# =============================================================================


def render_overview(cases: list[dict]) -> None:
    summary = aggregate_summary(cases)
    st.subheader("Headline metrics")
    metric_keys = [
        "case_pass",
        "route_correct",
        "tool_selection_correct",
        "tool_arguments_correct",
        "approval_correct",
        "guardrail_correct",
    ]
    columns = st.columns(len(metric_keys))
    for column, key in zip(columns, metric_keys):
        entry = summary["metrics"][key]
        rate = entry["rate"]
        column.metric(
            METRIC_LABELS[key],
            f"{rate:.0%}" if rate is not None else "N/A",
            help=f"{entry['passed']}/{entry['total']} applicable cases",
        )
    recall = summary["required_tool_recall"]
    st.caption(
        f"{summary['cases']} cases"
        + (f" · required-tool recall {recall:.0%}" if recall is not None else "")
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Confusion matrix")
        st.caption("Expected route chain (rows) vs. actual route chain (columns)")
        confusion_rows = summary["route_confusion"]
        if confusion_rows:
            matrix = (
                pd.DataFrame(confusion_rows)
                .pivot_table(index="expected", columns="actual", values="count", fill_value=0)
            )
            st.dataframe(matrix.style.background_gradient(cmap="Blues", axis=None), width="stretch")
        else:
            st.caption("No route data in this run.")
    with right:
        st.subheader("Single-agent vs. multi-agent")
        breakdown = breakdown_by(cases, agent_count_label)
        st.dataframe(breakdown, width="stretch", hide_index=True)
        if not breakdown.empty:
            st.bar_chart(breakdown.set_index("group")["case_pass_rate"])

    st.subheader("Results by specialist")
    specialists = sorted({route for case in cases for route in case.get("expected_routes", [])})
    if not specialists:
        st.caption("No specialist routes recorded in this run.")
    else:
        # Specialists need membership testing (a multi-agent case counts
        # toward every specialist it involves), not breakdown_by's
        # single-label partition, so this builds rows directly.
        rows = []
        for specialist in specialists:
            subset = [case for case in cases if specialist in case.get("expected_routes", [])]
            specialist_summary = aggregate_summary(subset)
            rows.append(
                {
                    "specialist": specialist,
                    "cases": len(subset),
                    "case_pass_rate": specialist_summary["metrics"]["case_pass"]["rate"],
                    "route_accuracy": specialist_summary["metrics"]["route_correct"]["rate"],
                    "tool_selection_accuracy": specialist_summary["metrics"]["tool_selection_correct"]["rate"],
                    "tool_argument_accuracy": specialist_summary["metrics"]["tool_arguments_correct"]["rate"],
                }
            )
        by_specialist = pd.DataFrame(rows)
        st.dataframe(by_specialist, width="stretch", hide_index=True)
        st.bar_chart(by_specialist.set_index("specialist")["case_pass_rate"])


def render_cases_table(cases: list[dict]) -> None:
    df = pd.DataFrame(cases)

    st.subheader("Filter")
    filter_columns = st.columns(4)
    categories = sorted(df["category"].unique())
    category_filter = filter_columns[0].multiselect("Category", categories, default=categories)
    all_tags = sorted({tag for tags in df["tags"] for tag in tags})
    tag_filter = filter_columns[1].multiselect("Tags (any match)", all_tags)
    status_filter = filter_columns[2].selectbox("Status", ["All", "Passed", "Failed"])
    specialists = sorted({route for routes in df["expected_routes"] for route in routes})
    specialist_filter = filter_columns[3].multiselect("Specialist", specialists)

    visible = df[df["category"].isin(category_filter)]
    if tag_filter:
        visible = visible[visible["tags"].apply(lambda tags: any(tag in tags for tag in tag_filter))]
    if status_filter == "Passed":
        visible = visible[visible["case_pass"]]
    elif status_filter == "Failed":
        visible = visible[~visible["case_pass"]]
    if specialist_filter:
        visible = visible[
            visible["expected_routes"].apply(
                lambda routes: any(specialist in routes for specialist in specialist_filter)
            )
        ]

    st.caption(f"{len(visible)} of {len(df)} cases match the current filters.")
    if not visible.empty:
        filtered_summary = aggregate_summary(visible.to_dict("records"))
        rate = filtered_summary["metrics"]["case_pass"]["rate"]
        st.caption(f"Case pass rate for this filtered set: {rate:.0%}" if rate is not None else "")

    display_columns = [
        "id",
        "category",
        "tags",
        "case_pass",
        "route_correct",
        "tool_selection_correct",
        "tool_arguments_correct",
        "approval_correct",
        "guardrail_correct",
        "expected_routes",
        "actual_routes",
        "duration_ms",
    ]
    st.dataframe(visible[display_columns], width="stretch", hide_index=True)


def render_case_detail(cases: list[dict]) -> None:
    ids = [case["id"] for case in cases]
    selected_id = st.selectbox("Case", ids, key="detail_case_select")
    case = next(entry for entry in cases if entry["id"] == selected_id)
    expected = case.get("expected", {})

    st.markdown(f"**Query:** {case.get('query', '')}")
    st.markdown(f"**Category:** {case['category']} · **Tags:** {', '.join(case.get('tags', []))}")

    st.subheader("Route")
    left, right = st.columns(2)
    left.markdown("**Expected**")
    left.code(" → ".join(expected.get("routes", [])) or "(none — FINISH)")
    right.markdown("**Actual**")
    right.code(" → ".join(case.get("actual_routes", [])) or "(none — FINISH)")
    st.markdown(f"Route correct: {verdict_icon(case.get('route_correct'))}")

    st.subheader("Tools")
    tool_spec = expected.get("tools", {})
    required = tool_spec.get("required", [])
    actual_calls = [entry for entry in case.get("tool_trace", []) if entry.get("event") == "call"]
    if required or actual_calls:
        exp_col, act_col = st.columns(2)
        with exp_col:
            st.markdown("**Expected**")
            if required:
                for spec in required:
                    count_suffix = f" ×{spec['min_count']}" if spec.get("min_count", 1) != 1 else ""
                    agent_suffix = f" ({spec['agent']})" if spec.get("agent") else ""
                    st.write(f"- `{spec.get('tool')}`{agent_suffix}{count_suffix}")
                    if "arguments" in spec:
                        st.json(spec["arguments"])
            else:
                st.caption("No required tools asserted.")
            if tool_spec.get("forbidden"):
                st.markdown("**Forbidden:** " + ", ".join(tool_spec["forbidden"]))
        with act_col:
            st.markdown("**Actual**")
            if actual_calls:
                for call in actual_calls:
                    agent_suffix = f" ({call['agent']})" if call.get("agent") else ""
                    st.write(f"- `{call.get('tool')}`{agent_suffix}")
                    if call.get("arguments"):
                        st.json(call["arguments"])
            else:
                st.caption("No tool calls recorded.")
    else:
        st.caption("No tool assertions or calls for this case.")
    st.markdown(
        f"Tool selection: {verdict_icon(case.get('tool_selection_correct'))} · "
        f"Tool arguments: {verdict_icon(case.get('tool_arguments_correct'))} · "
        f"Tool order: {verdict_icon(case.get('tool_order_correct'))}"
    )

    st.subheader("Approval")
    expected_approvals = expected.get("approvals")
    if expected_approvals is None and "approval" in expected:
        expected_approvals = [expected["approval"]]
    actual_approvals = case.get("approvals", [])
    if expected_approvals or actual_approvals:
        exp_col, act_col = st.columns(2)
        exp_col.markdown("**Expected**")
        exp_col.json(expected_approvals) if expected_approvals else exp_col.caption("(none)")
        act_col.markdown("**Actual**")
        act_col.json(actual_approvals) if actual_approvals else act_col.caption("(none)")
        st.markdown(f"Approval correct: {verdict_icon(case.get('approval_correct'))}")
    else:
        st.caption("No approval assertion for this case.")

    st.subheader("Guardrail")
    st.markdown(
        f"Expected: `{expected.get('guardrail', 'n/a')}` · "
        f"Actual: `{case.get('actual_guardrail', 'n/a')}` · "
        f"{verdict_icon(case.get('guardrail_correct'))}"
    )

    st.subheader("Final verdict")
    if case.get("case_pass"):
        st.success("PASS")
    else:
        st.error("FAIL")
    failures = case.get("failures", [])
    if failures:
        st.markdown("**Failure reason(s):**")
        for reason in failures:
            st.write(f"- {reason}")
    if case.get("error"):
        st.markdown("**Uncaught error:**")
        st.code(case["error"])

    with st.expander("Full answer"):
        st.write(case.get("answer") or "No answer recorded.")
    with st.expander("Full tool trace (raw)"):
        st.json(case.get("tool_trace", []))
    with st.expander("Project state (raw)"):
        st.json(case.get("project", {}))


def render_failures(cases: list[dict]) -> None:
    failing = [case for case in cases if not case.get("case_pass")]
    st.subheader(f"{len(failing)} of {len(cases)} cases failed")
    if not failing:
        st.success("No failing cases in this run.")
        return

    counts = dict.fromkeys(ASSERTION_LABELS.values(), 0)
    counts["Runtime error"] = 0
    for case in failing:
        for field, label in ASSERTION_LABELS.items():
            if case.get(field) is False:
                counts[label] += 1
        if case.get("error"):
            counts["Runtime error"] += 1

    st.markdown("**Which assertion failed, across all failing cases** (one case may fail more than one)")
    counts_df = pd.DataFrame(
        [{"assertion": label, "failing_cases": count} for label, count in counts.items() if count > 0]
    ).sort_values("failing_cases", ascending=False)
    if not counts_df.empty:
        st.bar_chart(counts_df.set_index("assertion")["failing_cases"])

    st.markdown("**Failing cases**")
    for case in failing:
        with st.expander(f"{case['id']} — {case['category']}"):
            st.write(f"Query: {case.get('query', '')}")
            for reason in case.get("failures", []):
                st.write(f"- {reason}")


def render_run_comparison(run_dirs: list[Path], default_dir: Path) -> None:
    if len(run_dirs) < 2:
        st.info("Need at least two saved runs to compare.")
        return

    left_col, right_col = st.columns(2)
    default_index_a = run_dirs.index(default_dir)
    dir_a = left_col.selectbox(
        "Run A", run_dirs, index=default_index_a, format_func=lambda path: path.name, key="compare_a"
    )
    default_index_b = min(default_index_a + 1, len(run_dirs) - 1)
    dir_b = right_col.selectbox(
        "Run B", run_dirs, index=default_index_b, format_func=lambda path: path.name, key="compare_b"
    )

    run_a = load_run(dir_a)
    run_b = load_run(dir_b)
    if run_a["schema"] != "v2" or run_b["schema"] != "v2":
        st.warning("Both runs must use the current schema (case_results.jsonl) to compare.")
        return

    summary_a = aggregate_summary(run_a["cases"])
    summary_b = aggregate_summary(run_b["cases"])

    rows = []
    for key, label in METRIC_LABELS.items():
        rate_a = summary_a["metrics"][key]["rate"]
        rate_b = summary_b["metrics"][key]["rate"]
        rows.append(
            {
                "metric": label,
                dir_a.name: rate_a,
                dir_b.name: rate_b,
                "delta": (rate_b - rate_a) if rate_a is not None and rate_b is not None else None,
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.subheader("Cases that changed verdict")
    cases_a = {case["id"]: case for case in run_a["cases"]}
    cases_b = {case["id"]: case for case in run_b["cases"]}
    common_ids = sorted(set(cases_a) & set(cases_b))
    changed = [
        {"id": case_id, dir_a.name: cases_a[case_id]["case_pass"], dir_b.name: cases_b[case_id]["case_pass"]}
        for case_id in common_ids
        if cases_a[case_id]["case_pass"] != cases_b[case_id]["case_pass"]
    ]
    if changed:
        st.dataframe(pd.DataFrame(changed), width="stretch", hide_index=True)
    else:
        st.caption("No case flipped pass/fail status between these two runs.")

    only_a = set(cases_a) - set(cases_b)
    only_b = set(cases_b) - set(cases_a)
    if only_a:
        st.caption(f"Only in {dir_a.name}: {', '.join(sorted(only_a))}")
    if only_b:
        st.caption(f"Only in {dir_b.name}: {', '.join(sorted(only_b))}")


# =============================================================================
# RAG retrieval evaluation (reads Assignment_8's saved RAGAS runs directly)
# =============================================================================


def list_rag_run_directories() -> list[Path]:
    if not RAG_RUNS_DIRECTORY.exists():
        return []
    return sorted(
        (
            path
            for path in RAG_RUNS_DIRECTORY.glob("*")
            if path.is_dir() and (path / "predictions.jsonl").exists()
        ),
        reverse=True,
    )


def list_ranking_run_directories() -> list[Path]:
    if not RAG_RUNS_DIRECTORY.exists():
        return []
    return sorted(
        (
            path
            for path in RAG_RUNS_DIRECTORY.glob("*")
            if path.is_dir() and (path / "per_query.csv").exists() and (path / "summary.json").exists()
        ),
        reverse=True,
    )


def render_rag_tab() -> None:
    st.caption(
        f"Reads saved runs from `{RAG_RUNS_DIRECTORY}` — the sibling Assignment_8 "
        "RAG evaluator's own output. This tab only displays those files; it doesn't "
        "run retrieval, reranking, or RAGAS scoring itself."
    )
    ragas_subtab, ranking_subtab = st.tabs(
        ["Answer Quality (RAGAS)", "Retrieval Ranking (Precision/Recall/MRR/NDCG)"]
    )
    with ragas_subtab:
        render_ragas_subtab()
    with ranking_subtab:
        render_ranking_subtab()


def render_ragas_subtab() -> None:
    rag_runs = list_rag_run_directories()
    if not rag_runs:
        st.info(
            "No RAGAS runs found. Use Assignment_8's own `dashboard.py` to generate "
            "predictions and RAGAS scores under `runs/<name>/`."
        )
        return

    selected_dir = st.selectbox("RAGAS run", rag_runs, format_func=lambda path: path.name, key="ragas_run_select")
    predictions_path = selected_dir / "predictions.jsonl"
    metrics_path = selected_dir / "metrics.csv"
    predictions = pd.DataFrame(
        [json.loads(line) for line in predictions_path.read_text().splitlines() if line.strip()]
    )
    metrics = pd.read_csv(metrics_path) if metrics_path.exists() else pd.DataFrame()

    if metrics.empty:
        st.warning("This run has predictions but no RAGAS metrics yet.")
    else:
        for name in RAG_METRIC_NAMES:
            if name not in metrics.columns:
                metrics[name] = pd.NA
        if "id" not in metrics.columns and len(metrics) == len(predictions):
            # metrics.csv is a positional RAGAS export with no id column;
            # Assignment_8's own dashboard makes the same row-order assumption.
            metrics = metrics.copy()
            metrics["id"] = predictions["id"].to_numpy()

        columns = st.columns(len(RAG_METRIC_NAMES))
        for column, name in zip(columns, RAG_METRIC_NAMES):
            values = pd.to_numeric(metrics[name], errors="coerce")
            column.metric(name.replace("_", " ").title(), f"{values.mean():.3f}" if values.notna().any() else "N/A")
            column.caption(f"{values.notna().sum()}/{len(values)} scored")

        st.subheader("Scores by question")
        display_columns = (["id"] if "id" in metrics.columns else []) + RAG_METRIC_NAMES
        st.dataframe(metrics[display_columns], width="stretch", hide_index=True)

    if not predictions.empty:
        st.subheader("Inspect a question")
        selected_question_id = st.selectbox("Question ID", predictions["id"].tolist())
        row = predictions[predictions["id"] == selected_question_id].iloc[0]
        st.write("**Question:**", row.get("query", ""))
        st.write("**Expected answer:**", row.get("expected_answer", ""))
        st.write("**Generated answer:**", row.get("answer", ""))
        st.write("**Latency:**", f"{row.get('latency_ms', 'n/a')} ms")
        contexts = row.get("contexts") or []
        if contexts:
            st.write("**Retrieved contexts:**")
            for index, context in enumerate(contexts, 1):
                with st.expander(f"Context {index}: {context.get('source_id', '?')}"):
                    st.write(context.get("text", ""))
                    st.caption(context.get("location", ""))


RANKING_METRIC_LABELS = {
    "precision": "Precision",
    "recall": "Recall",
    "mrr": "MRR",
    "ndcg": "NDCG",
}


def _ranking_metric_key(name: str) -> tuple[str, str]:
    """Split e.g. "precision_at_5" into a display label and its @k suffix."""

    for prefix, label in RANKING_METRIC_LABELS.items():
        if name == prefix:
            return label, ""
        if name.startswith(prefix + "_at_"):
            return label, name.removeprefix(prefix)  # "_at_5"
    return name.replace("_", " ").title(), ""


def render_ranking_subtab() -> None:
    ranking_runs = list_ranking_run_directories()
    if not ranking_runs:
        st.info(
            "No retrieval ranking runs found. Generate one from Assignment_8: "
            "`python -m evaluation.run_ranking_evaluation --k 5` — it compares "
            "pre-reranker (RRF) and post-reranker (cross-encoder) precision@k, "
            "recall@k, MRR, and NDCG@k."
        )
        return

    selected_dir = st.selectbox(
        "Ranking run", ranking_runs, format_func=lambda path: path.name, key="ranking_run_select"
    )
    summary = json.loads((selected_dir / "summary.json").read_text())
    st.caption(
        f"Dataset: {summary.get('dataset', 'unknown')} · "
        f"{summary.get('questions', '?')} questions · k={summary.get('k', '?')}"
    )

    st.subheader("Pre-reranker (RRF) vs. post-reranker (cross-encoder)")
    metric_names = list(summary.get("metrics", {}))
    columns = st.columns(len(metric_names)) if metric_names else []
    for column, name in zip(columns, metric_names):
        entry = summary["metrics"][name]
        label, suffix = _ranking_metric_key(name)
        pre, post, change = entry["pre_reranker"], entry["post_reranker"], entry["absolute_change"]
        column.metric(f"{label}{suffix}", f"{post:.3f}", delta=f"{change:+.3f} vs. pre-rerank")
        column.caption(f"pre-rerank: {pre:.3f}")

    st.subheader("Scores by question")
    per_query = pd.read_csv(selected_dir / "per_query.csv")
    st.dataframe(per_query, width="stretch", hide_index=True)

    rankings_path = selected_dir / "rankings.jsonl"
    if rankings_path.exists():
        st.subheader("Inspect a question's ranked results")
        rankings = [
            json.loads(line) for line in rankings_path.read_text().splitlines() if line.strip()
        ]
        rankings_by_id = {entry["id"]: entry for entry in rankings}
        selected_ranking_id = st.selectbox("Question ID", list(rankings_by_id), key="ranking_question_select")
        entry = rankings_by_id[selected_ranking_id]
        st.write("**Question:**", entry.get("query", ""))
        pre_col, post_col = st.columns(2)
        with pre_col:
            st.markdown("**Pre-reranker ranking (RRF)**")
            st.json(entry.get("pre_rerank", []))
        with post_col:
            st.markdown("**Post-reranker ranking (cross-encoder)**")
            st.json(entry.get("post_rerank", []))


# =============================================================================
# Page
# =============================================================================

st.set_page_config(page_title="Evaluation Dashboard", layout="wide")
st.title("Evaluation Dashboard")
st.caption(
    "Saved run history for System A's agent evaluation and the RAG retrieval "
    "evaluation, in one place. For live, interactive routing checks instead, "
    "use routing_dashboard.py."
)

with st.sidebar:
    st.header("Run System A evaluation")
    run_name = st.text_input("Run name", "agent_eval")

    dataset_cases = load_cases(DATASET) if DATASET.exists() else []
    all_categories = sorted({case["category"] for case in dataset_cases})
    all_tags = sorted({tag for case in dataset_cases for tag in case.get("tags", [])})
    all_case_ids = sorted(case["id"] for case in dataset_cases)

    scope = st.radio(
        "Which cases", ["All cases", "Filter by category / tag", "Specific case IDs"]
    )
    category_selection: list[str] = []
    tag_selection: list[str] = []
    case_id_selection: list[str] = []
    if scope == "Filter by category / tag":
        category_selection = st.multiselect("Categories (empty = all)", all_categories)
        tag_selection = st.multiselect(
            "Tags (empty = all)", all_tags,
            help="A case must carry ALL selected tags to match — same AND semantics as the CLI's repeated --tag flag.",
        )
    elif scope == "Specific case IDs":
        case_id_selection = st.multiselect("Case IDs", all_case_ids)

    exclude_requires = st.checkbox("Exclude cases requiring System B / DigiKey", value=True)
    fail_fast = st.checkbox("Stop at first failure", value=False)

    if dataset_cases:
        preview_args = argparse.Namespace(
            case_ids=case_id_selection or None,
            categories=category_selection or None,
            tags=tag_selection or None,
            exclude_requires=exclude_requires,
        )
        try:
            matched = select_cases(dataset_cases, preview_args)
            st.caption(f"{len(matched)} of {len(dataset_cases)} cases match this selection.")
        except ValueError as error:
            matched = []
            st.caption(str(error))

    if st.button("Run evaluation", type="primary", disabled=not dataset_cases or not matched):
        args = [sys.executable, str(RUNNER), "--run-name", run_name]
        for category in category_selection:
            args += ["--category", category]
        for tag in tag_selection:
            args += ["--tag", tag]
        for case_id in case_id_selection:
            args += ["--case", case_id]
        if exclude_requires:
            args.append("--exclude-requires")
        if fail_fast:
            args.append("--fail-fast")
        with st.spinner(f"Running {len(matched)} case(s)..."):
            process = subprocess.run(
                args,
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

agent_tab, rag_tab = st.tabs(["Agent Evaluation (System A)", "RAG Retrieval Evaluation"])

with agent_tab:
    run_dirs = list_run_directories()
    if not run_dirs:
        st.info("No saved runs yet. Start one from the sidebar.")
    else:
        selected_dir = st.selectbox(
            "Saved run", run_dirs, format_func=lambda path: path.name, key="agent_run_select"
        )
        run = load_run(selected_dir)
        metadata = run["metadata"]
        st.caption(
            f"Status: {metadata.get('status', 'unknown')} · "
            f"Started: {metadata.get('started_at', 'unknown')} · "
            f"Dataset: {metadata.get('dataset', 'unknown')}"
        )

        if run["schema"] == "legacy":
            st.warning(
                "This run uses an older schema (one expected/actual route only, no "
                "tool/argument/approval granularity). Re-run with the current "
                "evaluator to get full metrics."
            )
            st.dataframe(run["legacy_df"], width="stretch", hide_index=True)
        elif run["schema"] == "empty":
            st.warning("This run has no saved case results yet.")
            st.json(metadata)
        else:
            cases = run["cases"]
            overview_tab, cases_tab, detail_tab, failures_tab, compare_tab = st.tabs(
                ["Overview", "Cases", "Case Detail", "Failures", "Compare Runs"]
            )
            with overview_tab:
                render_overview(cases)
            with cases_tab:
                render_cases_table(cases)
            with detail_tab:
                render_case_detail(cases)
            with failures_tab:
                render_failures(cases)
            with compare_tab:
                render_run_comparison(run_dirs, selected_dir)

with rag_tab:
    render_rag_tab()
