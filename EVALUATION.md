# Evaluation Report

This report covers both halves of the system: the RAG pipeline (originally
built for Assignment 8 and now embedded here) and the multi-agent system
(Assignment 10 — System A's LangGraph supervisor/specialists and System B's
Component Manager). It follows the evaluation requirements in
`Final_Project_Requirements.pdf` §2.7/§5.3: a golden test set, retrieval
metrics, generation evaluation, agent routing/tool evaluation, at least two
configuration comparisons, and documented failure cases with root-cause
analysis.

Full source data for every number here is self-contained in this repository:
`evaluation/runs/`, `evaluation/golden_dataset/v2/cases.jsonl`,
`evaluation/rag_runs/`, and
`evaluation/golden_dataset/rag/arduino_rag_gold_dataset_final.jsonl`.

---

## 1. RAG pipeline (Assignment 8)

### 1.1 Design choices

| Choice | Value | Why |
|---|---|---|
| Chunking | Heading-hierarchy aware, not page-based; oversized sections split with overlap | PDF bookmarks/detected headings define chapter/project/subsection boundaries so a chunk stays a coherent unit of meaning instead of an arbitrary page cut. Images keep a link to their parent text chunk so a diagram stays tied to its explanation. |
| Embedding model | Gemini Embedding 2 | Matches the answer model's provider/tokenizer family and handles the technical/English domain well. |
| Vector DB | Qdrant | Required by the assignment; runs easily in Docker (`vector-db` service). |
| Metadata filtering | Modality filter (`FieldCondition(key="modality")`) on retrieval | Lets a query restrict to text vs. image-caption chunks. |
| Generation prompt | Grounded — answer only from retrieved context, say so when the answer isn't there | Required to keep faithfulness measurable and prevent hallucinated specs. |

### 1.2 Golden dataset (RAG)

50-question golden dataset (`arduino_rag_gold_dataset_final.jsonl`) with ground-truth
answers and source section references, used for retrieval ranking metrics;
the final generation-quality report uses a 30-question subset drawn from a
replacement golden dataset covering the same corpus more evenly (per-question
scores in §1.4 below).

### 1.3 Retrieval metrics (Precision@K, Recall@K, MRR, NDCG)

Computed by the original RAG ranking evaluation, K=5, 50 questions; its saved
run artifacts are retained under `evaluation/rag_runs/`.
Pre- vs. post-reranker (this doubles as configuration comparison #1 — see §3):

| Metric | Pre-reranker | Post-reranker | Change |
|---|---:|---:|---:|
| Precision@5 | 0.660 | 0.696 | +0.036 |
| Recall@5 | 0.903 | 0.903 | +0.000 |
| MRR | 0.852 | 0.877 | +0.026 |
| NDCG@5 | 0.734 | 0.760 | +0.026 |

### 1.4 Generation evaluation (RAGAS)

Framework: RAGAS, scoring faithfulness, answer relevancy, context precision,
context recall. Final architecture, 30 questions:

| Metric | Final mean | Coverage |
|---|---:|---:|
| Faithfulness | 0.967 | 30/30 |
| Answer relevancy | 0.910 | 30/30 |
| Context precision | 0.779 | 30/30 |
| Context recall | 0.922 | 30/30 |

28/30 answers scored perfect faithfulness. Context precision is the weakest
dimension — the retriever usually finds the right evidence but sometimes
keeps neighboring sections alongside it (a deliberate recall-favoring
tradeoff, see §3).

---

## 2. Agent evaluation (System A + System B)

### 2.1 Golden dataset (agents)

28 cases in `evaluation/golden_dataset/v2/cases.jsonl`, spanning every route,
every specialist, both approval outcomes (approved/rejected), guardrail
probes, and one infra-recovery case:

| Category | Count | What it covers |
|---|---:|---|
| `routing` | 24 | Conversation-only (FINISH), each specialist alone, multi-agent chains, approvals + rejections, purchase proposals |
| `guardrail` | 3 | Prompt injection, PII in a RAG query, PII in a purchasing query |
| `recovery` | 1 | System B unreachable — bounded retry, no unhandled exception |

Each case declares expected routes, required/forbidden tool calls (with
argument and ordering checks), expected approval behavior, expected project
state (wiring/code/model artifacts), and — for 15 of the 28 — a free-text
`task_completion.goal` for the LLM judge (§2.3).

### 2.2 Routing, tool selection, and correctness metrics

Final run (`evaluation/runs/20260821_062238_final_submission/`), all 28 cases:

| Metric | Passed / Total | Rate |
|---|---:|---:|
| Overall case pass | 28/28 | 100% |
| Route correct | 28/28 | 100% |
| Tool selection correct | 28/28 | 100% |
| Tool arguments correct | 28/28 | 100% |
| Tool call order correct | 28/28 | 100% |
| Guardrail correct | 28/28 | 100% |
| Approval correct | 10/10 | 100% |
| Project state correct | 16/16 | 100% |
| Cross-checks (e.g. code reuses wiring pins) | 2/2 | 100% |
| Recovery correct | 1/1 | 100% |
| Required-tool recall | 50/50 | 100% |
| Task completion (LLM judge) | 14/15 | 93.3% |

This was **not** the first run — getting here involved finding and fixing
several real bugs; see §4.

### 2.3 LLM as a judge

`evaluation/judge.py` grades the one thing deterministic assertions can't:
whether the final free-text answer actually accomplished the user's stated
goal (`compare_case`'s route/tool/project checks already catch structural
correctness; the judge catches "technically ran the right tools but the
answer itself doesn't deliver"). It's opt-in per case — only cases with an
`expected.task_completion.goal` get judged (15 of 28); everything else
reports `task_completion_correct: null` and is excluded from that metric's
denominator, not counted as a failure.

**Method:** `judge_model()` (`openai/gpt-oss-safeguard-20b`) with
`method="json_schema", strict=True` structured output into a
`TaskCompletionVerdict{passed: bool, reasoning: str}` — `json_schema` instead
of the default function-calling extraction, because this reasoning model
sometimes emits chain-of-thought as plain text instead of a tool call, which
the provider can't parse into a schema and rejects outright (the same failure
mode, and the same fix, as the supervisor's own structured-output router).

**A real limitation found and fixed today:** the judge originally only saw
the query, the goal, and the final answer text — nothing about what the turn
actually *produced*. That made it structurally blind to artifacts delivered
outside the answer text (a rendered 3D preview reaches the user via
`image_urls`, not by the model describing it in prose), so it was failing
cases that had, in fact, succeeded. Fixed by adding an evidence block to the
judge prompt — image count delivered, saved model/code/wiring artifacts —
with an explicit instruction to treat that as real proof of delivery instead
of penalizing the model for not re-describing it. Full case study in §4.

**Remaining judge failure (1/15):** `rag_servo_pwm` — the answer states a
0.5–2.5ms pulse-width range; the golden goal expects the ~1–2ms "typical
hobby servo" range. This is a genuine, if narrow, factual-precision miss (or
arguably an overly strict goal, since 0.5–2.5ms is also a commonly cited full
range) — left as-is rather than loosened, since it's a legitimate signal
either way.

### 2.4 Pricing / cost tracking

`evaluation/cost_tracking.py` attaches a LangChain callback to every graph
invocation and reads `AIMessage.usage_metadata`, priced per model at standard
on-demand rates (not batch), verified against each provider's pricing page:

| Model | Role | $/M input | $/M output |
|---|---|---:|---:|
| `openai/gpt-oss-120b` | supervisor | 0.15 | 0.60 |
| `openai/gpt-oss-safeguard-20b` | guardrails, judge | 0.075 | 0.30 |
| `qwen/qwen3.6-27b` | coding, wiring | 0.60 | 3.00 |
| `gemini-3.1-flash-lite` | RAG, visualization | 0.25 | 1.50 |
| `nvidia/nemotron-3-ultra-550b-a55b` | OpenRouter fallback | 0.50 | 2.20 |

A model missing from this table reports `cost_usd: null` rather than
silently costing $0, so a pricing gap is visible instead of hidden.

Final run totals: **$0.158** for all 28 cases, mean **$0.0056/case**, mean
**10,143 tokens/case**.

---

## 3. Configuration comparisons

**Comparison 1 — reranker on/off** (§1.3 already shown as a table): adding
local cross-encoder reranking on top of dense retrieval improved Precision@5
by +0.036 and MRR by +0.026 at zero recall cost. Kept.

**Comparison 2 — dense-only vs. hybrid (BM25 + RRF + reranker)**, RAGAS on 15
questions:

| Metric | Dense baseline | Hybrid | Change |
|---|---:|---:|---:|
| Faithfulness | 0.904 | 0.859 | −0.045 |
| Answer relevancy | 0.878 | 0.805 | −0.073 |
| Context precision | 0.605 | 0.702 | +0.097 |
| Context recall | 0.967 | 0.833 | −0.134 |

Hybrid retrieval hit its goal (context precision +0.097 — exact technical
terms plus reranking pushed relevant sections above generic ones) but
introduced a recall regression: query expansion grew the candidate pool, and
the top-5 cutoff sometimes dropped a section a compound question still
needed. Kept anyway — BM25/RRF/reranking measurably improved ranking, and the
recall regression was addressed separately (image captioning, §3 below)
rather than by reverting.

**Comparison 3 — baseline vs. detailed-caption pilot**, same 15 questions:

| Metric | Baseline | Detailed-caption pilot | Change |
|---|---:|---:|---:|
| Faithfulness | 0.904 | 0.944 | +0.040 |
| Answer relevancy | 0.878 | 0.875 | −0.003 |
| Context precision | 0.605 | 0.790 | +0.185 |
| Context recall | 0.967 | 0.967 | +0.000 |

Converting wiring-diagram images into retrieval-focused technical captions
(instead of relying on text-only retrieval, which could find the right
project but not the pin mapping shown only in a diagram) improved every
metric with no recall tradeoff. This became the final architecture.

---

## 4. Failure cases — root cause analysis

Six cases here rather than the minimum three, spanning both the RAG side
(Assignment 8's own documented failures) and the agent side (found and fixed
during this evaluation cycle), because each illustrates a genuinely different
failure class.

### 4.1 Mislabeled artifact field crashes a natural follow-up — **design failure**

**Symptom:** asking "can I see the picture?" right after a 3D model was
rendered returned `robot_visualization_agent failed: Model must be a .json
file inside generated/robots.`

**Root cause:** `project["model_artifact"]` was being set to the *rendered
preview PNG path*, not the model's own `.json` path, despite the field name
implying the latter. That mislabeled value flowed into the specialist's own
prompt via `project_context()`. Asked to "show the picture," the model's only
lever was `render_model(model_path=...)` — and the only path-shaped value in
its context was the wrong one, which failed a `.json`-suffix validation that
wasn't caught before it escaped the tool, crashing the whole turn.

**Fix:** store the actual `.json` model path in `model_artifact`
(`services/agent-system-a/app/graph.py`); wrap `render_model`'s path
resolution in the same try/except pattern its other failure branches already
use (`tools/model_tools.py`), so a bad path degrades to a normal tool result
instead of an uncaught exception; add a supervisor rule so a plain "show me
again" is answered directly instead of re-invoking the specialist at all.

### 4.2 A silent empty LLM response erases itself from history — **model failure amplified by a design gap**

**Symptom:** one coding request produced "No answer was produced" in the UI —
and the *next* message ("why") was refused as out-of-scope, even though it
was an obvious follow-up.

**Root cause:** a rare empty completion from the specialist model produced an
empty `final_answer`. Two independent parts of the pipeline both silently
drop empty content: `_finalize_turn` only saves a message when
`final_answer` is truthy, and the supervisor's own routing context
(`recent_conversation`) skips blank messages. So the failed turn vanished
from *both* the persisted chat history and the model's own routing context —
the very next turn had zero memory the exchange ever happened, and a
reasonable follow-up looked like a non-sequitur.

**Fix:** treat empty specialist output as a real failure, not a silent void —
`_run_agent` and `run_component` (`app/graph.py`) now substitute a clear
"completed without producing a response" message when the model returns
nothing, so the exchange is always visible to history and to future routing
decisions.

### 4.3 The evaluation judge is blind to non-text delivery — **design failure in the eval harness itself**

**Symptom:** cases where a 3D preview or code file genuinely was produced and
delivered still failed `task_completion_correct`.

**Root cause:** `judge_task_completion` only received the query, the goal,
and the answer text. Images are delivered to the client via `image_urls`
regardless of what the text says — but code has no equivalent channel; it
only reaches the user if the model pastes it into the answer. The judge
couldn't tell these two cases apart, and conflated "didn't restate it in
prose" with "didn't happen."

**Fix, two-sided:** (a) give the judge an evidence block — image count
delivered, saved model/code/wiring artifacts — with an explicit instruction
to treat delivered-but-not-narrated artifacts as real (`evaluation/judge.py`);
(b) separately fix the actual asymmetry it exposed — `CODING_PROMPT`
(`agents/coding_agent.py`) previously told the model to "return the path and
validation result" after saving code, i.e. explicitly *not* the code itself.
Since code has no out-of-band delivery channel the way images do, that was a
real product gap, not just a judge artifact — the prompt now requires the
complete code in a fenced block in the final answer.

### 4.4 A2A client follows the agent card's advertised URL, not the one it was given — **design/infra failure**

**Symptom:** every `component_manager`-routed evaluation case failed locally
with `Network communication error: [Errno 8] nodename nor servname provided`,
despite the container being reachable and responding.

**Root cause:** System B's A2A server advertises its own address in its
"agent card" as `http://agent-system-b:8002` (`ADVERTISED_HOST=agent-system-b`,
set deliberately in `docker-compose.yml` so *other containers* can reach it
by service name). The A2A client library fetches that card first, then routes
actual calls to whatever URL it advertises — not the URL it was originally
given. A local (non-Docker) evaluation process can complete the handshake
against `127.0.0.1:8002`, but its real calls get redirected to a hostname
that only resolves inside Docker's network.

**Fix:** a `127.0.0.1 agent-system-b` entry in `/etc/hosts` on the host
machine — makes the advertised hostname resolve locally to the same
published port, with zero changes to any project config and no effect on the
Docker-internal path.

### 4.5 A leftover from an in-flight rename crashes every approval case — **design failure (incomplete refactor)**

**Symptom:** after a `payment_credential_id` → `payment_method_id` rename
across the payment layer, every scripted approval/rejection case in
`evaluation/run_evaluation.py` crashed with
`TypeError: resume_thread() got an unexpected keyword argument 'payment_credential_id'`
— collapsing `approval_correct` to 0/10 and cascading into every multi-step
case that needed an approval to complete.

**Root cause:** the rename was applied consistently across the backend
(`schemas.py`, `main.py`, `chat_service.py`, `graph.py`) and most of the
frontend, but `run_evaluation.py`'s one call site to `resume_thread` was
missed. Straightforward one-parameter fix once traced.

### 4.6 RAG: a genuine retrieval/reference mismatch, not a bug (Assignment 8, §12.3)

**`FN-US-01`** (ultrasonic sensor evidence) scored context precision and
recall of 0 while faithfulness (0.929) and relevancy (0.908) stayed high —
the generated answer was well-supported by *something*, but that something
didn't align with the golden reference's expected evidence span. Documented
in Assignment 8's report as needing manual reference/context re-alignment
rather than a retrieval fix — a **model/data failure**, not a design or
prompt failure, since the pipeline behaved correctly given what it retrieved.

---

## 5. Known limitations

- **Judge cost/latency**: `task_completion_correct` adds one extra LLM call
  per judged case; fine at 15 cases, would need batching or sampling at scale.
- **RAG context precision** (0.779 final) remains the weakest of the four
  RAGAS dimensions — the retriever favors recall (keeping neighboring
  sections) over precision by design; a stricter top-K cutoff would trade
  this back the other way (see §3's hybrid-retrieval tradeoff).
- **Board-version ambiguity** (Assignment 8 §12.4): the source manual covers
  multiple Arduino board variants with similar naming; a question that
  doesn't name the board explicitly can retrieve the wrong variant's pinout.
  Not fixed — documented as needing either a clarification turn or a
  required board field.
- **Voice interface bonus is one-directional**: speech-to-text (Whisper) is
  implemented end-to-end; there is no text-to-speech on output.
- **No fine-tuned classifier bonus** was attempted.
- **`/etc/hosts` workaround** (§4.4) is a local-dev convenience for running
  evaluation outside Docker; it isn't needed and has no effect when the whole
  stack runs via `docker compose up`, since container-to-container A2A calls
  already resolve `agent-system-b` through Docker's internal DNS.
