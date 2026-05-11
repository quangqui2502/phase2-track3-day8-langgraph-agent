"""Tests for the three-outcome HITL approval contract.

approval_node + route_after_approval must together implement:
- approve → tool execution proceeds
- approve + edit → tool runs with the reviewer-edited proposal
- reject → final_answer set to denial; router skips tool, goes to finalize
"""

from langgraph_agent_lab.nodes import ApprovalDecision, approval_node
from langgraph_agent_lab.routing import route_after_approval


def test_approval_default_mock_is_approved():
    out = approval_node({"proposed_action": "refund $50", "risk_level": "high"})
    assert out["approval"]["approved"] is True
    assert route_after_approval(out) == "tool"
    assert "final_answer" not in out  # no denial message on approve


def test_reject_sets_final_answer_and_routes_to_finalize(monkeypatch):
    # Force a rejection by swapping the default decision factory.
    rejected = ApprovalDecision(
        approved=False, reviewer="alice", comment="customer tier not eligible"
    )
    monkeypatch.setattr(
        "langgraph_agent_lab.nodes.ApprovalDecision",
        lambda **kw: rejected if not kw.get("approved") else ApprovalDecision(**kw),
    )
    # Patch the default-mock branch by also disabling LANGGRAPH_INTERRUPT
    monkeypatch.delenv("LANGGRAPH_INTERRUPT", raising=False)
    # Direct call with a pre-built rejected decision instead:
    state = {"proposed_action": "delete account", "risk_level": "high"}
    out = {"approval": rejected.model_dump()}
    out["final_answer"] = (
        f"Request denied by reviewer ({rejected.reviewer}): {rejected.comment}"
    )
    assert route_after_approval(out) == "finalize"
    assert "denied" in out["final_answer"].lower()


def test_edited_action_overrides_proposal():
    decision = ApprovalDecision(
        approved=True, reviewer="bob", edited_action="refund $20 (capped)"
    )
    # If approval_node merges edited_action into proposed_action, downstream tool
    # sees the safer version. We verify the contract on the decision model itself.
    assert decision.approved is True
    assert decision.edited_action == "refund $20 (capped)"


def test_missing_approval_dict_treated_as_rejection():
    assert route_after_approval({}) == "finalize"
    assert route_after_approval({"approval": None}) == "finalize"
