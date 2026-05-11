# Day 08 Lab Report — LangGraph Agentic Orchestration

## 1. Student

- **Name:** 2A202600305 - Trần Quang Quí (quangqui2502)
- **Repo:** https://github.com/quangqui2502/phase2-track3-day8-langgraph-agent
- **Commit:** `4258100`
- **Date:** 2026-05-11

## 2. Architecture

The graph is an 11-node state machine that classifies a support ticket, dispatches it through one of five routes, and enforces production-grade controls (HITL approval, bounded retries, dead-letter, durable checkpoints).

```
START → intake → classify → ◇ route_after_classify
                            ├── simple        → answer → finalize → END
                            ├── tool          → tool → evaluate → ◇ route_after_evaluate
                            │                                       ├── success      → answer → finalize → END
                            │                                       └── needs_retry  → retry (loop)
                            ├── missing_info  → clarify → finalize → END
                            ├── risky         → risky_action → approval → ◇ route_after_approval
                            │                                              ├── approved → tool → ...
                            │                                              └── rejected → finalize → END
                            └── error         → retry → ◇ route_after_retry
                                                         ├── attempt<max  → tool → evaluate (loop)
                                                         └── attempt≥max  → dead_letter → finalize → END
```

**Why LangGraph (not LCEL):** the `tool → evaluate → retry → tool` cycle and the `approval → reject → finalize` branch require **cycles + conditional edges**. LCEL is a unidirectional pipe — it cannot express these flows without bespoke orchestration.

## 3. State schema

State is a `TypedDict` with explicit reducers on append-only fields. Mixing semantics is the most common bug in LangGraph projects, so I documented every field's contract.

| Field | Reducer | Why |
|---|---|---|
| `thread_id`, `scenario_id`, `query` | overwrite | identity — set once at intake, never appended |
| `route`, `risk_level` | overwrite | current classification only; previous values are irrelevant |
| `attempt`, `max_attempts` | overwrite | numeric counter — we want the latest value, not a sum |
| `final_answer`, `pending_question`, `proposed_action`, `approval`, `evaluation_result` | overwrite | latest decision wins |
| `messages` | `add` (append) | conversation/log trail |
| `tool_results` | `add` (append) | one entry per tool call, including retries |
| `errors` | `add` (append) | accumulating failure log per attempt |
| `events` | `add` (append) | full audit trail for grading + debugging |

## 4. Scenario results

From `outputs/metrics.json` (sqlite checkpointer):

- **Total scenarios:** 7
- **Success rate:** **100%** (7/7)
- **Avg nodes visited:** 6.43
- **Total retries:** 3
- **Total interrupts (HITL):** 2
- **Resume success:** ✅ (state history reconstructed from sqlite after run)

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
| S01_simple | simple | simple | ✅ | 0 | 0 |
| S02_tool | tool | tool | ✅ | 0 | 0 |
| S03_missing | missing_info | missing_info | ✅ | 0 | 0 |
| S04_risky | risky | risky | ✅ | 0 | 1 |
| S05_error | error | error | ✅ | 2 | 0 |
| S06_delete | risky | risky | ✅ | 0 | 1 |
| S07_dead_letter | error | error | ✅ | 1 | 0 |

**Tests:** 25/25 pass (`pytest tests/`). Coverage: routing (6), state (2), graph smoke (2), classify (6), approval flow (4), retry bounds (4), metrics (1).

## 5. Failure analysis

### 5.1 Bounded retry — preventing infinite loops

The naive retry router (`if attempt > max_attempts`) is a classic bug: with `max_attempts=1`, after one retry `attempt=1`, `1 > 1` is False → loops forever. **Fix:** use `>=`. Tested explicitly in `test_router_uses_gte_not_gt`. S07 (`max_attempts=1`) verifies the boundary by hitting dead_letter on attempt 1.

I also annotated the retry event with `next_route` metadata so the audit log explains *why* a run terminated — easier postmortem than reconstructing routing logic from code.

### 5.2 Risky action without approval

The original starter used substring matching (`"refund" in query`) which would (a) miss synonyms (`"cancel"`, `"revoke"`, `"wipe"`) and (b) false-positive on words like `"preFUNDed"`. **Fix:** token-set intersection with a curated `RISKY_KEYWORDS` set, prioritized over tool/error (test: `test_risky_priority_over_tool` proves `"Check status then refund order 12345"` routes to risky). This guarantees any potentially dangerous action hits the approval gate — even when a tool keyword co-occurs.

### 5.3 Reviewer rejection silently routing to clarify

Original `route_after_approval` sent rejected actions to `clarify` — confusing, because the user wasn't lacking info, the reviewer denied the action. **Fix:** rejection now sets `final_answer` to a denial message in `approval_node` and routes directly to `finalize`. Three outcomes are supported via `ApprovalDecision(approved, edited_action, comment)`.

## 6. Persistence / recovery evidence

**Checkpointer:** `SqliteSaver` on `outputs/checkpoints.db`.

**Connection lifecycle fix:** `SqliteSaver.from_conn_string()` returns a context manager — using it directly produced `_GeneratorContextManager` and crashed `graph.compile()`. Resolved by instantiating a `sqlite3.Connection` manually and passing it to `SqliteSaver(conn)` (see `persistence.py:20-31`).

**Evidence:**

```bash
$ ls -la outputs/checkpoints.db
-rw-r--r-- 1 quangqui staff 292K checkpoints.db

$ sqlite3 outputs/checkpoints.db "SELECT COUNT(*), COUNT(DISTINCT thread_id) FROM checkpoints;"
59|7       # 59 checkpoint rows across 7 thread_ids — one per scenario
```

**Cross-process resume demo** (`scripts/demo_resume.py`):
1. Process A: `graph.invoke(initial_state(s), config={thread_id})` writes 6 checkpoints.
2. Process B: fresh `build_graph()` + same DB + same thread_id → `graph.get_state_history(config)` returns the same 6 snapshots with correct `next` markers.

This proves state survives process boundaries — the foundation for crash-resume in production.

The CLI verifies this automatically and writes `resume_success: true` to metrics when the checkpointer is sqlite/postgres.

## 7. Extension work

Completed:

- **SQLite persistence** — replaced default `MemorySaver`; documented connection-string trap; demo script (`scripts/demo_resume.py`).
- **Real HITL via `interrupt()`** — `scripts/demo_interrupt.py` lets a human approve/reject/edit a risky action at runtime; graph pauses and resumes from the checkpoint. Enable with `LANGGRAPH_INTERRUPT=true`.
- **Three-outcome approval contract** — `ApprovalDecision` now supports `approved`, `edited_action`, and rejection-with-comment, each routed independently.
- **Retry observability** — every retry event carries `attempt`, `max_attempts`, and `next_route` metadata for postmortem analysis.
- **14 new unit tests** — guard the routing policy against hidden scenarios (synonyms, substring traps, co-occurring keywords, missing state).

Not done (would require more time):

- Postgres checkpointer (interface stubbed in `persistence.py`).
- Time-travel replay UI from `get_state_history()`.
- Parallel fan-out (two mock tools merged).
- LangSmith tracing.

## 8. Improvement plan — what I'd productionize first

1. **Replace keyword classify_node with an LLM classifier.** Heuristics are brittle — a slightly reworded risky query (`"please zero out this account"`) won't match my set. An LLM with a strict JSON schema + a low-confidence fallback to `missing_info` would generalize much better, with the same routing contract.

2. **Approval timeout + escalation.** Currently `approval_node` blocks indefinitely on `interrupt()`. Production should attach a deadline (e.g., 30 minutes), escalate to a second reviewer, then fail-safe to rejection. This is a real failure mode every HITL system hits.

3. **Structured tool results, not strings.** `tool_results: list[str]` puts parsing burden on every downstream node. Replace with `list[ToolResult]` (Pydantic model: `name`, `args`, `output`, `error`, `latency_ms`) — gives `evaluate_node` real fields to judge instead of substring-checking `"ERROR" in latest`.

4. **Exponential backoff between retries.** The retry event already carries `attempt`; the missing piece is a delay node or sleep before the next tool call (`delay = base * 2 ** (attempt - 1)`). Critical for any real external API that rate-limits.

5. **LangSmith tracing.** Free observability — every node call, every state delta, every retry, visualized. Worth one line of config in production.
