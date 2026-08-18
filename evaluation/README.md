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

## Dashboards

- `dashboard.py` reviews **saved** runs: routing/tool/approval/guardrail
  accuracy, a route confusion matrix, results by specialist and by
  single-vs-multi-agent, failure classification, a filterable case table, a
  detailed per-case view (expected vs. actual route/tools/arguments/approval),
  and run-to-run comparison. It also reads the sibling Assignment_8 project's
  saved RAGAS runs (`RAG_PROJECT_PATH/runs/*/metrics.csv`) in a second tab, so
  both evaluation families are visible in one place without needing
  Assignment_8's own dashboard running.

  ```bash
  .venv/bin/streamlit run evaluation/dashboard.py
  ```

- `routing_dashboard.py` drives the **live** graph directly for fast
  iteration while tuning prompts or adding specialists — no saved run file
  needed. Use `dashboard.py` to review what actually happened afterward.

  ```bash
  .venv/bin/streamlit run evaluation/routing_dashboard.py
  ```

Runs saved before this evaluator's current schema (no `case_results.jsonl`,
only `results.csv` with a single `expected_route`/`actual_route` pair) still
appear in `dashboard.py`'s run selector, but only as a raw table with a
warning — routing/tool/approval/guardrail metrics require the current
schema, so re-run those cases with today's evaluator to get full metrics.
