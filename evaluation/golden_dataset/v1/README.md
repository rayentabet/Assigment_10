# Golden Dataset v1 (archived)

This dataset is retained for historical reference only. Its purchase cases use
tools from the retired local-supplier workflow and must not be used for current
evaluation. The active dataset is `../v2/cases.jsonl`.

36 cases in `cases.jsonl` (one JSON object per line), covering every route the
system currently has: `rag_agent`, `coding_agent`, `robot_visualization_agent`,
`wiring_agent`, `component_manager`, plus FINISH (out-of-scope) and the input/
output guardrails — including the approval-interrupt pauses (`coding_agent`,
`robot_visualization_agent`, purchase proposals) and multi-turn conversations,
none of which the original 9-case `evaluation/queries.json` covered at all.

Not wired into `evaluation/run_evaluation.py` yet — that's a deliberate,
separate step. This is the dataset only.

**One real bug was found while building this** (not a hypothetical edge
case): see `wiring_duplicate_component_known_bug` below.

## Schema

Each line is one case:

| Field | Meaning |
|---|---|
| `id` | Unique, stable identifier. |
| `category` | `routing`, `guardrail`, `wiring`, `purchase`, or `a2a_recovery`. |
| `query` | The user message to send. Omit when `turns` is present. |
| `mode` | Omit for the normal graph flow. `"output_only"` skips the graph and checks `check_output()` directly against `candidate_output` (for testing the output guardrail without depending on a specialist's actual wording). |
| `candidate_output` | Required when `mode: "output_only"`. |
| `resume` | Optional. `{"approved": true/false}` — for cases that need exactly one follow-up turn: send `query`, then resume the paused thread with this decision. |
| `turns` | Optional, for cases needing **more than one** follow-up (e.g. propose → approve → check status). A list of steps, each either `{"query": "..."}` (send a new message on the same thread) or `{"resume": {"approved": bool}}` (resume the paused interrupt). Run in order; `expected` is checked against the state after the *last* turn. When present, supersedes `query`/`resume`. |
| `simulate` | Optional. A named failure condition the harness should inject before running this case (currently only `"component_manager_a2a_url_unreachable"`, used by the one `a2a_recovery` case). |
| `expected` | Category-shaped (see below). |
| `sensitive_value` | For PII cases: the string that must NOT appear in the output once masked. |
| `verify_against` | For `wiring` cases: which field of the graph result holds the value to check (`project.wiring`, or a specific tool's entry in `tool_trace`). |
| `requires` | Human-readable precondition, e.g. "component_manager/server.py running". Cases without this field need no external service. |
| `tags` | Free-form, for filtering/reporting. `"known-issue"` marks a case that currently fails against real code — see below. |
| `notes` | Why the case exists and, where relevant, exactly how `expected` was derived — see "How expected values were produced" below. |

### `expected` shape per category

- **`routing`**: `{"routes": [...], "guardrail": "passed"|"blocked"|"masked"}` for simple cases. Approval-flow cases add `{"pauses_for_approval": true, "approval_action": "coding_agent"|"robot_visualization_agent", "route_history_includes"|"route_history_excludes": "..."}` — the first turn must come back as `status == "approval_required"` with that `approval.action` *before* the specialist ever runs; only a `resume` with `approved: true` should make it appear in the final `route_history`. `routes` is the exact expected `route_history` — order matters for multi-step cases.
- **`guardrail`**: same shape as `routing`; these are really routing+guardrail cases that happen to probe safety behavior specifically.
- **`wiring`**: `{"board", "valid", "assignments", "conflicts", "warnings"}` for successful allocation cases, `{"board", "allocate_success", "unallocated_count", "unallocated_components"}` for capacity-limit cases, or `{"tool_result_found": false, "available_boards"|"available_components": [...]}` for unknown-board/component error paths. Check against `verify_against`, not the natural-language answer — the wiring tools are deterministic, so the answer text shouldn't matter.
- **`purchase`**: varies by case — proposal creation checks `purchase_proposal` fields (plus `total_formula`, see below); rejection/approval/multi-turn cases check `final_status`/`project_purchase_status`/`pending_purchase_proposal`/`tool_calls_include` after the last turn.
- **`a2a_recovery`**: `{"routes", "final_answer_contains", "no_crash"}`.

## How expected values were produced

- **Routing** (`routes`): read directly off `app/graph.py`'s current `SUPERVISOR_PROMPT` routing rules — not guessed, not run live (routing is LLM-mediated and only the *rule*, not one sample output, is the ground truth).
- **Wiring** (`assignments`/`valid`/`conflicts`/`warnings`/error paths): computed by directly invoking `tools/wiring_tools.py`'s `get_board_capabilities`, `get_component_requirements`, `allocate_pins` → `validate_wiring` → `format_wiring_plan` on 2026-08-14, bypassing the LLM entirely. These tools are pure functions over the static catalogs in `tools/data/`, so the values are exact and won't drift unless those catalogs change. Covers single-component, I2C bus sharing, SPI bus sharing (with the reserved-pin exemption), a 6-pin motor driver, a 4-component build, board-specific I2C numbering (Uno vs. Mega), unknown board, and unknown component.
- **Purchase totals**: deliberately *not* hardcoded. `component_manager/catalog.py::jittered_price` reseeds its price jitter from the current date, so a frozen number would go stale the next day. `purchase_create_proposal`'s `total_formula` note spells out the exact recomputation (same best-offer selection `create_purchase_proposal` itself uses, from `component_manager/tools.py`): for each supplier, `price = jittered_price(component_id, supplier_id)`, pick `min(price * quantity, tie-break lower base_delivery_days)`, `expected_total = round(price * quantity + SHIPPING_FEE, 2)`. Whoever wires this into the harness should import `component_manager.catalog` and reuse that logic rather than re-deriving it. `purchase_spending_limit_exceeded` uses a quantity (100 units) chosen to exceed the $200 default `spending_limit` regardless of the day's jitter, so that outcome is deterministic even without computing the exact rejected total.
- **The full approve-flow purchase case** reproduces a real run verified live against a Gemini-backed Component Manager on 2026-08-13 (real order `ORD-277f9d34fa34`), so it's a known-good scenario, not a guess.
- **Approval-flow cases** (`routing_coding_approval_*`, `routing_visualization_approval_*`, the full-chain case): read directly off `app/graph.py`'s `APPROVAL_REQUIRED_ROUTES` and `approve_action`/`route_approval` logic — `coding_agent` and `robot_visualization_agent` are the only two routes gated this way.

### Known issue: `wiring_duplicate_component_known_bug`

While computing the multi-component wiring cases above, requesting the same
component twice (e.g. two DC motors — the standard two-wheeled-robot case)
turned out to silently lose the first one's pin assignment:
`allocate_pins`' `assignments` dict is keyed by `component_key`, so the
second `"dc_motor"` entry overwrites the first, even though `used` correctly
reserved distinct pins for both under the hood. This case encodes the
*correct* expected behavior (two distinct motor entries) and is tagged
`known-issue` — it will fail until `tools/wiring_tools.py::allocate_pins` is
fixed to key by allocation instance, not just component type. Deliberately
not fixed here — this task was dataset-only.

## Versioning

Bump to `v2/` (new directory) when expectations change meaningfully — e.g. the
board/component catalogs change, pricing logic changes, or a route is
added/removed — so historical runs stay comparable against the dataset
version they were actually run against. Don't edit `v1/` in place once it's
been run against.
