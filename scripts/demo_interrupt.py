"""Real HITL demo using LangGraph's interrupt() primitive.

Run with: LANGGRAPH_INTERRUPT=true python scripts/demo_interrupt.py

Flow:
1. Graph runs until it hits approval_node, which calls interrupt(payload).
2. invoke() returns with __interrupt__ marker; we inspect the proposed action.
3. We resume with a decision dict; graph picks up exactly where it paused.
4. Same thread_id + checkpointer = state survives the pause.
"""

from __future__ import annotations

import os

os.environ["LANGGRAPH_INTERRUPT"] = "true"

from langgraph.types import Command  # noqa: E402

from langgraph_agent_lab.graph import build_graph  # noqa: E402
from langgraph_agent_lab.persistence import build_checkpointer  # noqa: E402
from langgraph_agent_lab.scenarios import load_scenarios  # noqa: E402
from langgraph_agent_lab.state import initial_state  # noqa: E402


def main() -> None:
    scenarios = load_scenarios("data/sample/scenarios.jsonl")
    risky = next(s for s in scenarios if s.id == "S04_risky")
    checkpointer = build_checkpointer("memory")
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": f"demo-{risky.id}"}}

    # Run until interrupt
    result = graph.invoke(initial_state(risky), config=config)
    interrupts = result.get("__interrupt__")
    if not interrupts:
        print("No interrupt fired — check approval_node wiring.")
        return

    payload = interrupts[0].value
    print(f"PAUSED at approval. Proposed: {payload}")
    print("Type a decision (approve / reject / edit <text>):")
    line = input("> ").strip().lower()

    if line.startswith("edit "):
        decision = {"approved": True, "reviewer": "demo", "edited_action": line[5:]}
    elif line.startswith("approve"):
        decision = {"approved": True, "reviewer": "demo"}
    else:
        decision = {"approved": False, "reviewer": "demo", "comment": "rejected via demo"}

    # Resume with the decision
    final = graph.invoke(Command(resume=decision), config=config)
    print(f"\nFINAL answer: {final.get('final_answer')}")
    print(f"Approval state: {final.get('approval')}")


if __name__ == "__main__":
    main()
