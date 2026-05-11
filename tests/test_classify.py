"""Tests for classify_node — guards the routing policy against hidden scenarios.

These cover edge cases the sample scenarios don't exercise:
- Co-occurring keywords (risky must win)
- Substring false positives ("preFUND" should NOT trigger refund)
- Synonym coverage (cancel, revoke, crash, unavailable)
- Vague pronoun + short query → missing_info
"""

from langgraph_agent_lab.nodes import classify_node


def _route(query: str) -> str:
    return classify_node({"query": query})["route"]


def test_risky_keywords_cover_synonyms():
    assert _route("Cancel my subscription now") == "risky"
    assert _route("Please revoke API access for user 42") == "risky"
    assert _route("Wipe all data for this account") == "risky"


def test_risky_priority_over_tool():
    # Co-occurring "refund" (risky) and "order" (tool) → risky must win.
    assert _route("Check status then refund order 12345") == "risky"


def test_no_substring_false_positives():
    # "preFUNDed" contains "fund" but is not a risky token. "ordering" contains "order".
    # Token match rules these out → simple route.
    assert _route("My account is preFUNDed and working well") == "simple"
    assert _route("I love ordering through your platform") == "simple"


def test_error_synonyms():
    assert _route("Service is unavailable right now") == "error"
    assert _route("The system crash happened twice today") == "error"


def test_missing_info_requires_short_and_pronoun():
    # Short + vague pronoun → missing_info
    assert _route("Can you fix that?") == "missing_info"
    assert _route("Why is this") == "missing_info"
    # Long query with pronoun → NOT missing_info (treated as simple)
    long_query = "Can you help me understand why this particular feature stopped working today"
    assert _route(long_query) == "simple"


def test_simple_default():
    assert _route("How do I reset my password?") == "simple"
    assert _route("What are your business hours") == "simple"
