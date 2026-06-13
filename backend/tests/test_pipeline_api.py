"""
Tests for /api/pipeline endpoints.

The LangGraph orchestrator and LLM calls are mocked — we only test
the HTTP layer, DB persistence, and stage snapshot logic.
"""

import pytest
from unittest.mock import patch, MagicMock


def _create_session(client, name="Pipeline Session"):
    resp = client.post("/api/sessions/", json={
        "name": name,
        "target_url": "https://www.saucedemo.com",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


def _mock_graph(stage="refinement", awaiting=False):
    """Return a mock compiled LangGraph graph that yields a minimal state."""
    graph = MagicMock()
    state = {
        "session_id": "test",
        "current_stage": stage,
        "awaiting_human": awaiting,
        "requirements": [],
        "clarification_questions": [],
        "clarification_answers": {},
        "test_cases": [],
        "generated_tests": {},
        "validation_results": [],
        "stage_history": [],
        "iteration_count": 0,
        "retry_count": 0,
        "error": None,
        "user_feedback": None,
    }
    # _run_pipeline uses graph.stream(), not graph.invoke()
    graph.stream.return_value = [state]
    graph.invoke.return_value = state
    graph.get_state_history.return_value = []
    # get_state() returns an object whose .next tuple is empty (not interrupted)
    mock_lg_state = MagicMock()
    mock_lg_state.next = ()
    mock_lg_state.config = {"configurable": {"checkpoint_id": None}}
    graph.get_state.return_value = mock_lg_state
    return graph


class TestStartPipeline:
    def test_start_returns_ok(self, client):
        sid = _create_session(client, "StartTest")
        with patch("backend.api.routes.pipeline.get_compiled_graph", return_value=_mock_graph()):
            resp = client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "User can log in",
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_start_unknown_session_returns_404(self, client):
        with patch("backend.api.routes.pipeline.get_compiled_graph", return_value=_mock_graph()):
            resp = client.post("/api/pipeline/start", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "raw_requirements": "anything",
            })
        assert resp.status_code == 404

    def test_start_creates_snapshot(self, client, db_session):
        from backend.models.orm import StageSnapshot
        sid = _create_session(client, "SnapshotTest")
        with patch("backend.api.routes.pipeline.get_compiled_graph", return_value=_mock_graph("refinement")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "User can log in",
            })
        snaps = db_session.query(StageSnapshot).filter(StageSnapshot.session_id == sid).all()
        assert len(snaps) >= 1
        assert snaps[0].stage == "refinement"

    def test_start_updates_session_stage(self, client, db_session):
        from backend.models.orm import Session as SessionModel
        sid = _create_session(client, "StageUpdateTest")
        with patch("backend.api.routes.pipeline.get_compiled_graph", return_value=_mock_graph("test_case_generation")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Cart feature",
            })
        session = db_session.query(SessionModel).filter(SessionModel.id == sid).first()
        assert session.current_stage == "test_case_generation"

    def test_start_sets_status_paused_when_awaiting_human(self, client, db_session):
        from backend.models.orm import Session as SessionModel
        sid = _create_session(client, "PausedTest")
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("clarification_wait", awaiting=True)):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Login feature",
            })
        session = db_session.query(SessionModel).filter(SessionModel.id == sid).first()
        assert session.status == "paused"


class TestResumePipeline:
    def test_resume_returns_ok(self, client):
        sid = _create_session(client, "ResumeTest")
        # First start it
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("clarification_wait", awaiting=True)):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Login",
            })
        # Then resume
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("test_case_generation")):
            resp = client.post("/api/pipeline/resume", json={
                "session_id": sid,
                "answer": {"answers": {"What is the role?": "standard_user"}},
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_resume_unknown_session_returns_404(self, client):
        with patch("backend.api.routes.pipeline.get_compiled_graph", return_value=_mock_graph()):
            resp = client.post("/api/pipeline/resume", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "answer": {},
            })
        assert resp.status_code == 404


class TestCheckpoints:
    def test_empty_checkpoints(self, client):
        sid = _create_session(client, "CheckpointEmpty")
        resp = client.get(f"/api/pipeline/{sid}/checkpoints")
        assert resp.status_code == 200
        assert resp.json()["checkpoints"] == []

    def test_checkpoints_after_start(self, client):
        sid = _create_session(client, "CheckpointFull")
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("refinement")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Some feature",
            })
        resp = client.get(f"/api/pipeline/{sid}/checkpoints")
        checkpoints = resp.json()["checkpoints"]
        assert len(checkpoints) == 1
        assert checkpoints[0]["stage"] == "refinement"

    def test_checkpoint_has_required_fields(self, client):
        sid = _create_session(client, "CheckpointFields")
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("validation")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Checkout flow",
            })
        cp = client.get(f"/api/pipeline/{sid}/checkpoints").json()["checkpoints"][0]
        assert "id" in cp
        assert "stage" in cp
        assert "created_at" in cp


class TestGetState:
    def test_state_none_before_start(self, client):
        sid = _create_session(client, "StateEmpty")
        resp = client.get(f"/api/pipeline/{sid}/state")
        assert resp.status_code == 200
        assert resp.json()["state"] is None

    def test_state_after_start(self, client):
        sid = _create_session(client, "StateFull")
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("code_generation")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Cart tests",
            })
        resp = client.get(f"/api/pipeline/{sid}/state")
        assert resp.json()["stage"] == "code_generation"
        assert resp.json()["state"] is not None


class TestEditStage:
    def test_edit_existing_snapshot(self, client):
        sid = _create_session(client, "EditTest")
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("test_case_generation")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Cart",
            })
        resp = client.patch(
            f"/api/pipeline/{sid}/stage/test_case_generation",
            json={"data": {"test_cases": [{"id": "TC-001", "title": "Edited TC"}]}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_edit_missing_stage_returns_404(self, client):
        sid = _create_session(client, "EditMissing")
        resp = client.patch(
            f"/api/pipeline/{sid}/stage/nonexistent_stage",
            json={"data": {}},
        )
        assert resp.status_code == 404


class TestReturnToCheckpoint:
    def test_return_to_checkpoint(self, client):
        sid = _create_session(client, "BacktrackTest")
        # Create two checkpoints
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("refinement")):
            client.post("/api/pipeline/start", json={
                "session_id": sid,
                "raw_requirements": "Login flow",
            })
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("test_case_generation")):
            client.post("/api/pipeline/resume", json={
                "session_id": sid,
                "answer": {},
            })

        # Get first checkpoint
        checkpoints = client.get(f"/api/pipeline/{sid}/checkpoints").json()["checkpoints"]
        assert len(checkpoints) >= 1
        first_cp = checkpoints[0]

        # Go back to it
        with patch("backend.api.routes.pipeline.get_compiled_graph",
                   return_value=_mock_graph("refinement")):
            resp = client.post("/api/pipeline/return-to-checkpoint", json={
                "session_id": sid,
                "checkpoint_id": first_cp.get("langgraph_checkpoint_id") or "mock-cp-id",
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
