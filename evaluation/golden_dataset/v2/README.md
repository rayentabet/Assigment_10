# Golden Dataset v2

This is the active System A evaluation dataset. It replaces v1, whose purchase
cases described the retired local-supplier workflow. The current Component
Manager uses DigiKey search, AP2-bound proposals, explicit human approval, and
sandbox ordering.

`cases.jsonl` contains 29 cases covering all five specialists, FINISH,
single- and multi-agent routing, tool selection, important tool arguments,
approval/rejection behavior, project artifacts, input guardrails, and A2A recovery.

## Assertion schema

Every case has `id`, `category`, `expected`, and `tags`, plus either `query` or
`turns`. A `turns` entry is a sequence of `{"query": "..."}` and
`{"resume": {"approved": true|false}}` operations on one thread.

The `expected` object may contain:

- `routes`: exact final `route_history`, in order. Repeated routes are failures.
- `guardrail`: input-guardrail result: `passed`, `masked`, or `blocked`.
- `tools.required`: required call assertions. `agent`, `tool`, `min_count`, and
  an `arguments` subset are supported.
- `tools.ordered_subsequence`: tool names that must appear in this order; other
  calls may occur between them.
- `tools.forbidden`: tools that must never be called.
- `approval` or `approvals`: expected interrupt action and decision.
- `project`: recursive subset of the final structured project state.
- `final`: `non_empty`, case-insensitive `contains_all`, and `not_contains`.
- `cross_checks`: cross-artifact invariants such as generated code reusing the
  pins stored in `project.wiring`.
- `recovery`: recovery properties for simulated failure cases.

Argument matcher objects such as `{"ends_with": ".ino"}` and
`{"non_empty": true}` describe predicates rather than literal values.

## Ground-truth policy

- Route labels follow the public responsibility boundaries in
  `app/graph.py::SUPERVISOR_PROMPT`, with exact ordering only where the user
  explicitly requests dependent work.
- Tool expectations come from each specialist's actual registered tools and
  prompt. System B expectations use only `check_component_availability`,
  `search_digikey`, `create_digikey_proposal`, `place_digikey_order`, and
  `get_digikey_order`.
- Deterministic wiring outputs come from `tools/wiring_tools.py` and the static
  board/component catalogs.
- Coding and visualization cases assert the graph's approval boundary before
  any file-writing or rendering tool can run.
- Output-only guardrail cases from v1 were removed because the current graph
  has no output-guardrail node or `check_output()` function.
- Purchase proposal cases stop at the `place_order` interrupt. They never fake
  approval credentials or submit an order as part of routing evaluation.

## External requirements

Cases with `requires` are filterable. `system_b_a2a` means the A2A service must
be running. `digikey_search_credentials` means DigiKey Product Information
sandbox credentials must also be configured. Cases without `requires` run
against System A alone, subject to its configured model/MCP dependencies.

The v1 directory remains only as historical evidence. New runners and
dashboards must use v2.
