"""Tests for retry/dead-letter logic — guards against infinite loops."""

from langgraph_agent_lab.nodes import retry_or_fallback_node
from langgraph_agent_lab.routing import route_after_retry


def test_retry_increments_attempt():
    out = retry_or_fallback_node({"attempt": 0, "max_attempts": 3})
    assert out["attempt"] == 1


def test_router_uses_gte_not_gt():
    # max_attempts=1: after one retry, attempt=1; must dead-letter (not loop forever).
    assert route_after_retry({"attempt": 1, "max_attempts": 1}) == "dead_letter"


def test_retry_event_carries_next_route_metadata():
    out = retry_or_fallback_node({"attempt": 0, "max_attempts": 1})
    event = out["events"][0]
    assert event["metadata"]["next_route"] == "dead_letter"

    out = retry_or_fallback_node({"attempt": 0, "max_attempts": 3})
    assert out["events"][0]["metadata"]["next_route"] == "tool"


def test_missing_max_attempts_defaults_to_three():
    # Defensive default — router shouldn't crash on partial state.
    assert route_after_retry({"attempt": 0}) == "tool"
    assert route_after_retry({"attempt": 3}) == "dead_letter"
