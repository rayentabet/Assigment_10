# Evaluation

The active System A suite is `golden_dataset/v2/cases.jsonl`. Run it from the
repository root:

```bash
PYTHONPATH=. .venv/bin/python -m evaluation.run_evaluation \
  --run-name system_a_final
```

Useful filters:

```bash
# Run without System B or DigiKey-dependent cases
PYTHONPATH=. .venv/bin/python -m evaluation.run_evaluation \
  --run-name system_a_local --exclude-requires

# Run one case
PYTHONPATH=. .venv/bin/python -m evaluation.run_evaluation \
  --run-name routing_smoke --case rag_ultrasonic_principle

# Run one category or cases carrying all requested tags
PYTHONPATH=. .venv/bin/python -m evaluation.run_evaluation \
  --run-name approvals --category routing --tag approval
```

Each run is saved under `evaluation/runs/<timestamp>_<name>/`:

- `metadata.json`: dataset, selected cases, models, timestamps, and run status.
- `case_results.jsonl`: complete auditable case records, including tools,
  approvals, project state, answer, and independent verdicts.
- `results.csv`: flat result table for dashboards and manual analysis.
- `summary.json`: aggregate metric rates, required-tool recall, and exact-route
  confusion rows.

One failing case does not stop the suite unless `--fail-fast` is supplied.
Partial results and summaries are rewritten after every case, so an interrupted
provider run remains inspectable.

The evaluator deliberately keeps route, tool selection, tool arguments, tool
order, approvals, guardrails, project state, and cross-artifact checks separate.
`case_pass` is the conjunction of the assertions applicable to that case; it is
not used as a substitute for the individual metrics.

Three more metrics are tracked but kept out of `case_pass` (reported, not
gating, until spot-checked as reliable):

- **Task completion**: for cases declaring `expected.task_completion.goal`,
  an LLM judge (`evaluation/judge.py`, `settings.judge_model`) grades whether
  the final answer actually accomplished the goal — not a string match.
- **Step efficiency**: for cases declaring `expected.min_steps`,
  `step_efficiency_ratio = iteration_count / min_steps` is reported per case
  and averaged in `summary.json`.
- **Cost per task**: every case's `graph.ainvoke()` call is wrapped with a
  token-usage collector (`evaluation/cost_tracking.py`), priced against
  `MODEL_PRICING` (Groq/Google/OpenRouter on-demand rates, verified live
  2026-08-20). `cost_usd` is `None` for any case using a model not in that
  table — e.g. after a model is swapped in `app/config.py` — rather than
  silently reporting $0. The run prints a warning listing any unpriced
  models it saw; re-verify and add rates there when that happens.

## Dashboard

`dashboard.py` reviews **saved** runs: routing/tool/approval/guardrail
accuracy, a route confusion matrix, results by specialist and by
single-vs-multi-agent, task completion / step efficiency / cost per task,
failure classification, a filterable case table, a detailed per-case view
(expected vs. actual route/tools/arguments/approval, plus judge reasoning),
and run-to-run comparison. It also reads the imported RAGAS and retrieval
ranking runs under `evaluation/rag_runs/` in a second tab, so both evaluation
families are visible without another repository.

```bash
.venv/bin/streamlit run evaluation/dashboard.py
```

Runs saved before this evaluator's current schema (no `case_results.jsonl`,
only `results.csv` with a single `expected_route`/`actual_route` pair) still
appear in `dashboard.py`'s run selector, but only as a raw table with a
warning — routing/tool/approval/guardrail metrics require the current
schema, so re-run those cases with today's evaluator to get full metrics.
