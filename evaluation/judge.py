"""LLM-judge task-completion grading for the v2 golden dataset.

Deterministic assertions (routes, tools, project state) already cover most of
what a case needs to check. Task completion is different: it asks whether the
free-text final answer actually accomplished the user's goal, which a
substring check can't reliably tell (an answer can be factually correct and
still fail the task, e.g. by refusing to give a total the user asked for).
This module grades that with an LLM judge instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

JUDGE_PROMPT = """You are grading whether an AI assistant's final answer \
accomplished the user's goal for one task. Judge only task completion: did \
the answer do what was asked? Do not penalize style, verbosity, or minor \
omissions unrelated to the stated goal.

The assistant's final text answer is not the only thing the user receives.
Some artifacts (rendered model previews, images) are delivered directly to the
user's client through a separate channel and are summarized in the evidence
below even when the answer text doesn't restate them. Treat that evidence as
real proof of delivery: do not fail a case solely for not re-describing an
artifact in prose when the evidence confirms it was produced and delivered.
Code has no such separate channel — it only reaches the user if it's actually
included in the final answer text.

User request:
{query}

What a correct answer must accomplish:
{goal}

Assistant's final answer:
{answer}

Additional evidence of what was actually produced this turn (not shown to the
user directly, but proof of what happened):
{evidence}

Did the final answer accomplish the goal?"""


def _evidence_summary(execution: dict) -> str:
    """Summarize what the turn actually produced, for artifacts the judge
    can't see in the answer text (images are delivered out-of-band; code is not).
    """

    result = execution.get("result") or {}
    project = result.get("project") or {}
    image_count = len(result.get("image_paths") or [])
    lines = [f"- Images delivered to the client this turn: {image_count}"]
    if project.get("model_artifact"):
        lines.append(f"- Saved 3D model artifact: {project['model_artifact']}")
    if project.get("code_artifact"):
        lines.append(f"- Saved code artifact: {project['code_artifact']}")
    if project.get("wiring"):
        lines.append(f"- Wiring plan valid: {project['wiring'].get('valid')}")
    return "\n".join(lines)


class TaskCompletionVerdict(BaseModel):
    passed: bool = Field(description="Whether the final answer accomplished the stated goal")
    reasoning: str = Field(description="One or two sentences explaining the verdict")


async def judge_task_completion(case: dict, execution: dict) -> dict:
    """Grade one case's final answer against its `expected.task_completion.goal`.

    Returns `{"task_completion_correct": None, "task_completion_reasoning": None}`
    for cases that don't declare a `task_completion` goal, so it stays opt-in
    per case exactly like `compare_final`/`compare_project` already are.
    """

    task_completion = case["expected"].get("task_completion")
    if not task_completion:
        return {"task_completion_correct": None, "task_completion_reasoning": None}

    from app.models import judge_model

    query = case.get("query") or next(
        (turn["query"] for turn in case.get("turns", []) if "query" in turn), ""
    )
    prompt = JUDGE_PROMPT.format(
        query=query,
        goal=task_completion["goal"],
        answer=execution.get("answer", ""),
        evidence=_evidence_summary(execution),
    )
    # method="json_schema" (not the default function-calling extraction) is what
    # keeps this reliable on a reasoning model: without it, gpt-oss-safeguard-20b
    # sometimes emits its chain-of-thought as plain text instead of a tool call,
    # which Groq can't parse into the schema and rejects with a 400. The
    # supervisor's own router (app/graph.py) hit the same failure mode and is
    # pinned the same way.
    judge = judge_model().with_structured_output(
        TaskCompletionVerdict, method="json_schema", strict=True
    )
    try:
        verdict = await judge.ainvoke(prompt)
    except Exception as error:  # noqa: BLE001 - one case's judge call must not abort the run
        return {
            "task_completion_correct": None,
            "task_completion_reasoning": f"judge error: {type(error).__name__}: {error}",
        }
    return {
        "task_completion_correct": verdict.passed,
        "task_completion_reasoning": verdict.reasoning,
    }
