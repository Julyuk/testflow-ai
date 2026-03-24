"""
LangGraph orchestrator — defines the TestFlow AI state machine.

Nodes:
  intake → refinement → [clarification_wait ↔ user] → test_case_gen
  → [review_wait ↔ user] → code_gen → validation → export → END

At any stage the user can trigger a "return to step N" which replays
the graph from the corresponding checkpoint stored in PostgreSQL.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.state import (
    TestFlowState, PipelineStage, RequirementStatus, TestCaseType, Priority
)

import warnings as _warnings
_warnings.filterwarnings("ignore", category=UserWarning, module=r"langgraph.*")
from backend.agents.requirements_agent import run_requirements_agent
from backend.agents.test_case_agent import run_test_case_agent
from backend.agents.test_generation_agent import run_test_generation_agent
from backend.agents.validation_agent import run_validation_agent
from backend.config.settings import settings


def _log(state: TestFlowState, agent: str, message: str, level: str = "info") -> None:
    """Broadcast an activity log event if a session_id is present."""
    session_id = state.get("session_id")
    if session_id:
        try:
            from backend.events import log_activity
            log_activity(session_id, agent, message, level)
        except Exception:
            pass


# ── node functions ────────────────────────────────────────────────────────────

def intake_node(state: TestFlowState) -> dict:
    _log(state, "orchestrator", "Pipeline started — normalizing requirements...")
    return {
        "current_stage": PipelineStage.REFINEMENT,
        "iteration_count": 0,
        "awaiting_human": False,
        "retry_count": 0,
    }


def refinement_node(state: TestFlowState) -> dict:
    _log(state, "requirements_agent", "Analyzing requirements with chain-of-thought reasoning...")
    result = run_requirements_agent(state)
    if result.get("clarification_questions"):
        _log(state, "requirements_agent",
             f"Found {len(result['clarification_questions'])} ambiguities — generating clarification questions.",
             "warning")
    else:
        count = len(result.get("requirements", []))
        _log(state, "requirements_agent",
             f"Structured {count} requirement(s) into User Story format.", "success")
    return result


def clarification_wait_node(state: TestFlowState) -> dict:
    """Pause execution — LangGraph interrupt() suspends here."""
    _log(state, "orchestrator", "Waiting for user to answer clarification questions...", "warning")
    from langgraph.types import interrupt
    answer = interrupt({
        "type": "clarification",
        "questions": state["clarification_questions"],
    })
    _log(state, "orchestrator", "Clarification answers received — resuming refinement.", "info")
    return {
        "clarification_answers": answer,
        "awaiting_human": False,
        "current_stage": PipelineStage.REFINEMENT,
    }


def requirements_review_node(state: TestFlowState) -> dict:
    """Pause execution — wait for user to review and approve structured requirements."""
    _log(state, "orchestrator", "Waiting for user to review structured requirements...", "warning")
    from langgraph.types import interrupt

    answer = interrupt({
        "type": "requirements_review",
        "requirements": state["requirements"],
    })
    # answer = { requirements: [...], action: "approve" }
    updated_reqs = answer.get("requirements", state["requirements"])
    # Fallback guard: if somehow empty reqs reach here, keep the existing ones
    has_content = any((r.get("user_story") or "").strip() for r in updated_reqs)
    if not has_content:
        _log(state, "orchestrator",
             "Received empty requirements on approval — keeping previous requirements.", "warning")
        updated_reqs = state["requirements"]

    count = len(updated_reqs)
    _log(state, "orchestrator",
         f"Requirements approved ({count}). Proceeding to test case generation.", "success")
    return {
        "requirements": updated_reqs,
        "awaiting_human": False,
        "current_stage": PipelineStage.TEST_CASE_GENERATION,
    }


def test_case_node(state: TestFlowState) -> dict:
    _log(state, "test_case_agent",
         "Generating test cases using EP, BVA, Decision Table and State Transition techniques...")
    result = run_test_case_agent(state)
    count = len(result.get("test_cases", []))
    _log(state, "test_case_agent", f"Generated {count} test case(s). Awaiting review.", "success")
    return result


def review_wait_node(state: TestFlowState) -> dict:
    _log(state, "orchestrator", "Waiting for user to review and approve test cases...", "warning")
    from langgraph.types import interrupt
    answer = interrupt({
        "type": "review",
        "test_cases": state["test_cases"],
    })
    feedback = answer.get("feedback", "")
    is_regenerate = bool(feedback and "regenerate" in feedback.lower())

    if is_regenerate:
        _log(state, "orchestrator", "User requested regeneration of test cases.", "warning")
        # Route back to test_case_gen — stage reflects actual next step
        next_stage = PipelineStage.TEST_CASE_GENERATION
    else:
        approved = [tc for tc in answer.get("test_cases", []) if tc.get("approved")]
        _log(state, "orchestrator",
             f"User approved {len(approved)} test case(s). Proceeding to code generation.", "success")
        next_stage = PipelineStage.CODE_GENERATION

    return {
        "user_feedback": feedback if is_regenerate else None,  # clear on approve to prevent stale routing
        "test_cases": answer.get("test_cases", state["test_cases"]),
        "awaiting_human": False,
        "current_stage": next_stage,
    }


def code_generation_node(state: TestFlowState) -> dict:
    approved = [tc for tc in state["test_cases"] if tc.get("approved", False)]
    count = len(approved) or len(state["test_cases"])
    _log(state, "test_generation_agent",
         f"Generating Python/Playwright code for {count} test case(s) using Page Object Model...")
    result = run_test_generation_agent(state)
    files = len(result.get("generated_tests", {}))
    _log(state, "test_generation_agent",
         f"Generated {files} file(s). Running validation...", "success")
    return result


def validation_node(state: TestFlowState) -> dict:
    _log(state, "validation_agent", "Running AST syntax check and pylint static analysis...")
    result = run_validation_agent(state)
    results = result.get("validation_results", [])
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    if passed == total:
        _log(state, "validation_agent", f"All {total} file(s) passed validation.", "success")
    else:
        failed = total - passed
        retry = state.get("retry_count", 0)
        _log(state, "validation_agent",
             f"{failed} file(s) failed validation (retry {retry}/3). Requesting code fix...", "error")
    return result


def export_node(state: TestFlowState) -> dict:
    _log(state, "orchestrator", "Pipeline complete. Artifacts ready for download.", "success")
    return {"current_stage": PipelineStage.COMPLETED}


# ── routing functions ─────────────────────────────────────────────────────────

def route_after_refinement(state: TestFlowState) -> str:
    if state.get("clarification_questions"):
        return "clarification_wait"
    return "requirements_review"


def route_after_clarification(state: TestFlowState) -> str:
    return "refinement"


def route_after_test_cases(state: TestFlowState) -> str:
    return "review_wait"


def route_after_review(state: TestFlowState) -> str:
    feedback = state.get("user_feedback", "")
    if feedback and "regenerate" in feedback.lower():
        return "test_case_gen"
    return "code_gen"


def route_after_validation(state: TestFlowState) -> str:
    results = state.get("validation_results", [])
    has_errors = any(not r.get("passed", True) for r in results)
    retry = state.get("retry_count", 0)
    if has_errors and retry < 3:
        return "code_gen"
    return "export"


# ── graph builder ─────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    graph = StateGraph(TestFlowState)

    graph.add_node("intake", intake_node)
    graph.add_node("refinement", refinement_node)
    graph.add_node("clarification_wait", clarification_wait_node)
    graph.add_node("requirements_review", requirements_review_node)
    graph.add_node("test_case_gen", test_case_node)
    graph.add_node("review_wait", review_wait_node)
    graph.add_node("code_gen", code_generation_node)
    graph.add_node("validation", validation_node)
    graph.add_node("export", export_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "refinement")
    graph.add_conditional_edges("refinement", route_after_refinement,
                                 {"clarification_wait": "clarification_wait",
                                  "requirements_review": "requirements_review"})
    graph.add_edge("clarification_wait", "refinement")
    graph.add_edge("requirements_review", "test_case_gen")
    graph.add_edge("test_case_gen", "review_wait")
    graph.add_conditional_edges("review_wait", route_after_review,
                                 {"test_case_gen": "test_case_gen",
                                  "code_gen": "code_gen"})
    graph.add_edge("code_gen", "validation")
    graph.add_conditional_edges("validation", route_after_validation,
                                 {"code_gen": "code_gen",
                                  "export": "export"})
    graph.add_edge("export", END)

    # NOTE: No interrupt_before here — interrupt() calls inside the nodes
    # are sufficient. Using both interrupt_before AND interrupt() inside
    # the same node causes a double-pause: the first resume answer is
    # discarded, and the pipeline hangs on the second unanswered interrupt.
    return graph.compile(checkpointer=checkpointer)


_graph_instance = None

import logging as _logging
_logger = _logging.getLogger(__name__)


def get_compiled_graph():
    """Return singleton graph — checkpointer state must persist across requests."""
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from psycopg_pool import ConnectionPool

        db_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

        # Register custom Enum types so LangGraph's msgpack serializer
        # can round-trip them without emitting "unregistered type" warnings.
        _serde = JsonPlusSerializer(
            allowed_msgpack_modules=[("backend.agents.state", "TestCaseType"),
                                     ("backend.agents.state", "Priority"),
                                     ("backend.agents.state", "RequirementStatus"),
                                     ("backend.agents.state", "PipelineStage")]
        )

        # PostgresSaver.setup() calls CREATE INDEX CONCURRENTLY which Postgres
        # forbids inside a transaction block.  Use a separate autocommit connection
        # purely for the one-time schema setup, then hand off to the pool.
        with psycopg.connect(db_url, autocommit=True) as setup_conn:
            PostgresSaver(setup_conn, serde=_serde).setup()

        # The pool is used for all subsequent checkpoint reads/writes.
        # psycopg_pool manages reconnection automatically.
        pool = ConnectionPool(conninfo=db_url, max_size=5, open=True)
        checkpointer = PostgresSaver(pool, serde=_serde)
        _graph_instance = build_graph(checkpointer)
        _logger.info("LangGraph checkpointer: PostgresSaver (durable)")
    except Exception as exc:
        _logger.warning(
            "PostgresSaver init failed (%s: %s) — falling back to MemorySaver. "
            "Checkpoints will be lost on restart and RAM will grow unbounded.",
            type(exc).__name__, exc,
        )
        _graph_instance = build_graph(checkpointer=MemorySaver())

    return _graph_instance
