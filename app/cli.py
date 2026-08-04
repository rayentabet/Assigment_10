"""Small command-line interface for the multi-agent graph."""

import asyncio
from uuid import uuid4

from app.guardrails import resume_guarded, run_guarded


async def run() -> None:
    user_input = input("What would you like to do?\n> ").strip()
    thread_id = str(uuid4())
    result = await run_guarded(user_input, thread_id=thread_id)

    if interrupts := result.get("__interrupt__"):
        request = interrupts[0].value
        print(f"\nApproval required: {request['reason']}")
        print(f"Action: {request['action']}")
        print(f"Task: {request['task']}")
        approved = input("Proceed? [y/N] ").strip().lower() in {"y", "yes"}
        result = await resume_guarded(thread_id, approved)

    print("\n" + (result.get("final_answer") or "Run paused."))
    print("\nRoute:", " -> ".join(result["route_history"]) or "blocked")
    print("Iterations:", result["iteration_count"])


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
