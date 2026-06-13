"""
Tests for LangGraph orchestrator routing logic.

Builds the graph WITHOUT a checkpointer (MemorySaver) and verifies
that routing functions direct the pipeline correctly.
"""

import pytest
from unittest.mock import patch, MagicMock
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.orchestrator import build_graph, route_after_refinement, route_after_review, route_after_validation
from backend.agents.state import PipelineStage


# ── Routing function unit tests ───────────────────────────────────────────────

class TestRouteAfterRefinement:
    def test_routes_to_clarification_when_questions_present(self):
        state = {"clarification_questions": ["What is the role?"]}
        assert route_after_refinement(state) == "clarification_wait"

    def test_routes_to_requirements_review_when_no_questions(self):
        state = {"clarification_questions": []}
        assert route_after_refinement(state) == "requirements_review"

    def test_routes_to_requirements_review_when_questions_key_missing(self):
        state = {}
        assert route_after_refinement(state) == "requirements_review"


class TestRouteAfterReview:
    def test_routes_to_code_gen_on_approve(self):
        state = {"user_feedback": "approve"}
        assert route_after_review(state) == "code_gen"

    def test_routes_to_code_gen_when_no_feedback(self):
        state = {"user_feedback": None}
        assert route_after_review(state) == "code_gen"

    def test_routes_to_test_case_gen_on_regenerate(self):
        state = {"user_feedback": "please regenerate these"}
        assert route_after_review(state) == "test_case_gen"

    def test_routes_to_test_case_gen_case_insensitive(self):
        state = {"user_feedback": "REGENERATE"}
        assert route_after_review(state) == "test_case_gen"


class TestRouteAfterValidation:
    def test_routes_to_export_when_all_pass(self):
        state = {
            "validation_results": [{"passed": True}],
            "retry_count": 0,
        }
        assert route_after_validation(state) == "export"

    def test_routes_to_code_gen_on_failure_within_retry_limit(self):
        state = {
            "validation_results": [{"passed": False}],
            "retry_count": 1,
        }
        assert route_after_validation(state) == "code_gen"

    def test_routes_to_export_when_retry_limit_reached(self):
        state = {
            "validation_results": [{"passed": False}],
            "retry_count": 3,
        }
        assert route_after_validation(state) == "export"

    def test_routes_to_export_on_empty_results(self):
        state = {"validation_results": [], "retry_count": 0}
        assert route_after_validation(state) == "export"


# ── Graph structure tests ──────────────────────────────────────────────────────

class TestGraphStructure:
    def test_graph_compiles_with_memory_checkpointer(self):
        graph = build_graph(checkpointer=MemorySaver())
        assert graph is not None

    def test_graph_compiles_without_checkpointer(self):
        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        graph = build_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "intake", "refinement", "clarification_wait", "requirements_review",
            "test_case_gen", "review_wait", "code_gen",
            "validation", "export",
        }
        assert expected.issubset(node_names)


# ── Integration: graph runs to first interrupt ───────────────────────────────

class TestGraphExecution:
    """Run the graph with mocked agents to verify stage sequencing."""

    def _make_state(self, session_id="test-session"):
        return {
            "session_id": session_id,
            "user_id": "test",
            "raw_requirements": "User can log in with valid credentials",
            "requirements": [],
            "clarification_questions": [],
            "clarification_answers": {},
            "test_cases": [],
            "generated_tests": {},
            "validation_results": [],
            "current_stage": "intake",
            "stage_history": [],
            "iteration_count": 0,
            "awaiting_human": False,
            "user_feedback": None,
            "error": None,
            "retry_count": 0,
            "app_url": "https://www.saucedemo.com",
        }

    def test_intake_transitions_to_refinement(self):
        """Intake → refinement → requirements_review interrupt (no clarification questions)."""
        def mock_refinement(state):
            return {
                "requirements": [{"id": "REQ-001", "raw_text": "login", "user_story": "As a user...", "acceptance_criteria": [], "status": "structured"}],
                "clarification_questions": [],
                "current_stage": PipelineStage.REQUIREMENTS_REVIEW,
                "awaiting_human": False,
            }

        graph = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "test-session"}}

        with patch("backend.agents.orchestrator.run_requirements_agent", side_effect=mock_refinement):
            result = graph.invoke(self._make_state(), config)

        # Graph pauses at requirements_review — requirements should be populated
        assert result["requirements"][0]["id"] == "REQ-001"

    def test_clarification_interrupt_fires_when_questions_present(self):
        """When refinement returns questions, graph should pause at clarification_wait."""
        def mock_refinement_with_questions(state):
            return {
                "requirements": [],
                "clarification_questions": ["What pages should be tested?"],
                "current_stage": PipelineStage.CLARIFICATION_WAIT,
                "awaiting_human": True,
            }

        graph = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "clarify-session"}}

        with patch("backend.agents.orchestrator.run_requirements_agent",
                   side_effect=mock_refinement_with_questions):
            result = graph.invoke(self._make_state("clarify-session"), config)

        assert result.get("clarification_questions") == ["What pages should be tested?"]
