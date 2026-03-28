"""
Pipeline management routes + WebSocket for real-time stage events.

Flow:
  POST /start                      → kick off pipeline
  POST /resume                     → send human answer, continue pipeline
  POST /return-to-checkpoint       → restore LangGraph checkpoint, re-run
  PATCH /{id}/stage/{stage}        → edit snapshot data before rerun
  GET  /{id}/checkpoints           → list all backtrack points
  GET  /{id}/state                 → current pipeline state
  POST /{id}/execute               → run generated tests with pytest
  GET  /{id}/executions            → execution history
  GET  /{id}/download              → download generated tests as ZIP
  GET  /{id}/ci/github-actions     → download GitHub Actions workflow YAML
  GET  /{id}/ci/azure-pipelines    → download Azure Pipelines YAML
  WS   /ws/{id}                    → receive real-time stage + activity events
"""

import asyncio
import io
import json
import re
import zipfile
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from backend.agents.orchestrator import get_compiled_graph
from backend.config.llm import get_llm
from backend.models.database import get_db
from backend.models.orm import Session as SessionModel, StageSnapshot, ExecutionResult
from backend.runner.executor import run_tests_streaming
from backend.ci.github_actions import generate_github_actions_workflow, generate_azure_pipelines_yaml
from backend import events as ev

router = APIRouter()

# Keys the edit_stage endpoint is allowed to modify — prevents arbitrary state injection.
_EDITABLE_KEYS = {"test_cases", "requirements", "generated_tests", "raw_requirements"}


def _save_snapshot(db: DBSession, session_id: str, stage: str, state: dict, checkpoint_id: str | None = None):
    snap = StageSnapshot(
        session_id=session_id,
        stage=stage,
        snapshot_data=state,
        langgraph_checkpoint_id=checkpoint_id,
    )
    db.add(snap)
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if session:
        session.current_stage = stage
        session.updated_at = datetime.utcnow()
    db.commit()


# ── request schemas ───────────────────────────────────────────────────────────

class StartPipelineRequest(BaseModel):
    session_id: str
    raw_requirements: str


class ResumeRequest(BaseModel):
    session_id: str
    answer: dict


class ReturnToCheckpointRequest(BaseModel):
    session_id: str
    checkpoint_id: str


class EditStageRequest(BaseModel):
    data: dict


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_session_or_404(session_id: str, db: DBSession) -> SessionModel:
    s = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


def _get_latest_snapshot(session_id: str, db: DBSession) -> StageSnapshot | None:
    return (
        db.query(StageSnapshot)
        .filter(StageSnapshot.session_id == session_id)
        .order_by(StageSnapshot.created_at.desc())
        .first()
    )


def _run_pipeline(graph, config: dict, input_state: Any, session_id: str, db: DBSession) -> dict:
    result: dict = {}
    saved_stages: set[str] = set()

    try:
        # Stream through all node executions — saves a snapshot at every stage change
        for state in graph.stream(input_state, config, stream_mode="values"):
            result = state
            stage = state.get("current_stage", "unknown")
            if stage and stage not in saved_stages:
                saved_stages.add(stage)
                checkpoint_id = None
                try:
                    # get_state() is O(1) — avoids the O(n) full history scan that
                    # get_state_history() performs and which causes quadratic slowdown
                    # as checkpoint count grows (called once per stage = O(n²) total).
                    lg_state = graph.get_state(config)
                    if lg_state:
                        checkpoint_id = lg_state.config["configurable"].get("checkpoint_id")
                except Exception:
                    pass
                snap = StageSnapshot(
                    session_id=session_id,
                    stage=stage,
                    snapshot_data=state,
                    langgraph_checkpoint_id=checkpoint_id,
                )
                db.add(snap)
                sess_row = db.query(SessionModel).filter(SessionModel.id == session_id).first()
                if sess_row:
                    sess_row.current_stage = stage
                    sess_row.updated_at = datetime.utcnow()
                db.commit()
                ev.broadcast(session_id, {"type": "stage_update", "stage": stage, "state": state})

    except Exception as exc:
        # Update session status to error so it doesn't stay stuck on "running"
        try:
            sess_row = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if sess_row:
                sess_row.status = "error"
                sess_row.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
        ev.broadcast(session_id, {
            "type": "stage_update",
            "stage": "error",
            "state": {**result, "current_stage": "error", "error": str(exc)},
        })
        raise

    # Final status update
    stage = result.get("current_stage", "unknown")
    sess_row = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if sess_row:
        if stage == "completed":
            sess_row.status = "completed"
        elif result.get("awaiting_human"):
            sess_row.status = "paused"
        else:
            sess_row.status = "running"
        sess_row.updated_at = datetime.utcnow()
        db.commit()

    return result


# ── pipeline endpoints ────────────────────────────────────────────────────────

@router.post("/start")
async def start_pipeline(req: StartPipelineRequest, db: DBSession = Depends(get_db)):
    session = _get_session_or_404(req.session_id, db)
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    initial_state = {
        "session_id": req.session_id,
        "user_id": "default",
        "raw_requirements": req.raw_requirements,
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
        "app_url": session.target_url or "https://www.saucedemo.com",
    }

    result = await run_in_threadpool(_run_pipeline, graph, config, initial_state, req.session_id, db)
    return {"status": "ok", "state": result}


def _ensure_interrupt_checkpoint(graph, config: dict, session_id: str, db: DBSession) -> None:
    """
    Guard against the case where the latest LangGraph checkpoint has no pending interrupt
    (e.g. because edit_stage previously called graph.update_state() and created a new
    checkpoint that cleared the interrupt marker).  When that happens, Command(resume=...)
    is treated as the *initial* input and the graph restarts from scratch with a partial
    state, causing KeyError on fields like raw_requirements.

    Recovery: if the latest checkpoint has nothing scheduled to run next (empty `next`),
    reload the most-recent DB snapshot and push it back into the graph via update_state
    using the interrupt node as the writer so the interrupt is reinstated.
    """
    # Interrupt node names — the ones that call interrupt() and pause
    INTERRUPT_NODES = {"clarification_wait", "requirements_review", "review_wait"}
    try:
        lg_state = graph.get_state(config)
        # `next` is the tuple of nodes that will run on the next tick.
        # An interrupted graph has the interrupt node listed in `next`.
        if lg_state and lg_state.next:
            return  # interrupt is still pending — nothing to do
    except Exception:
        pass

    # No pending interrupt — recover from the latest DB snapshot
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        return
    stage = snap.stage
    # Determine which interrupt node "owns" this stage
    interrupt_node = stage if stage in INTERRUPT_NODES else None
    if not interrupt_node:
        return
    try:
        graph.update_state(config, snap.snapshot_data, as_node=interrupt_node)
    except Exception:
        pass


@router.post("/resume")
async def resume_pipeline(req: ResumeRequest, db: DBSession = Depends(get_db)):
    _get_session_or_404(req.session_id, db)
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    # Recover interrupt checkpoint if it was clobbered by a prior update_state call
    await run_in_threadpool(_ensure_interrupt_checkpoint, graph, config, req.session_id, db)

    # Command(resume=...) passes the answer back to the interrupt() call point
    result = await run_in_threadpool(
        _run_pipeline, graph, config, Command(resume=req.answer), req.session_id, db
    )
    return {"status": "ok", "state": result}


@router.post("/return-to-checkpoint")
async def return_to_checkpoint(req: ReturnToCheckpointRequest, db: DBSession = Depends(get_db)):
    _get_session_or_404(req.session_id, db)
    graph = get_compiled_graph()
    config = {
        "configurable": {
            "thread_id": req.session_id,
            "checkpoint_id": req.checkpoint_id,
        }
    }
    result = await run_in_threadpool(_run_pipeline, graph, config, None, req.session_id, db)
    return {"status": "ok", "state": result}


class RestoreSnapshotRequest(BaseModel):
    snapshot_id: str


@router.post("/{session_id}/restore-checkpoint")
async def restore_checkpoint_state(
    session_id: str,
    req: RestoreSnapshotRequest,
    db: DBSession = Depends(get_db),
):
    """Restore pipeline state from a DB snapshot WITHOUT re-running any agents."""
    _get_session_or_404(session_id, db)
    snap = (
        db.query(StageSnapshot)
        .filter(StageSnapshot.id == req.snapshot_id, StageSnapshot.session_id == session_id)
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    # Update LangGraph in-memory state so next action starts from this point
    try:
        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": session_id}}
        graph.update_state(config, snap.snapshot_data)
    except Exception:
        pass

    # Determine the appropriate session status based on the restored stage
    stage = snap.stage
    if stage == "completed":
        new_status = "completed"
    elif stage in ("clarification_wait", "review_wait"):
        new_status = "paused"
    else:
        new_status = "paused"

    sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if sess:
        sess.current_stage = stage
        sess.status = new_status
        sess.updated_at = datetime.utcnow()
        db.commit()

    ev.broadcast(session_id, {"type": "stage_update", "stage": stage, "state": snap.snapshot_data})
    return {"status": "ok", "state": snap.snapshot_data, "stage": stage}


@router.patch("/{session_id}/stage/{stage}")
async def edit_stage(
    session_id: str,
    stage: str,
    req: EditStageRequest,
    db: DBSession = Depends(get_db),
):
    # Validate that only safe keys are being modified
    invalid_keys = set(req.data.keys()) - _EDITABLE_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Not allowed to edit field(s): {', '.join(sorted(invalid_keys))}",
        )

    # Match by exact stage name
    snap = (
        db.query(StageSnapshot)
        .filter(StageSnapshot.session_id == session_id, StageSnapshot.stage == stage)
        .order_by(StageSnapshot.created_at.desc())
        .first()
    )
    if not snap:
        # Fallback: find the most recent snapshot whose state has this current_stage value
        all_snaps = (
            db.query(StageSnapshot)
            .filter(StageSnapshot.session_id == session_id)
            .order_by(StageSnapshot.created_at.desc())
            .all()
        )
        snap = next(
            (s for s in all_snaps if s.snapshot_data.get("current_stage") == stage),
            None,
        )
    if not snap:
        raise HTTPException(status_code=404, detail=f"No snapshot for stage '{stage}'")

    snap.snapshot_data = {**snap.snapshot_data, **req.data}
    db.commit()

    # NOTE: We intentionally do NOT call graph.update_state() here.
    # Doing so would create a new LangGraph checkpoint without a pending interrupt,
    # which causes Command(resume=...) to restart the graph from scratch on the next
    # resume call (KeyError on raw_requirements and similar fields).
    # The DB snapshot is the authoritative store for edits; resume_pipeline recovers
    # the interrupt checkpoint from the DB snapshot if needed before resuming.

    return {"status": "ok", "stage": stage}


@router.get("/{session_id}/checkpoints")
async def list_checkpoints(session_id: str, db: DBSession = Depends(get_db)):
    snaps = (
        db.query(StageSnapshot)
        .filter(StageSnapshot.session_id == session_id)
        .order_by(StageSnapshot.created_at.asc())
        .all()
    )
    # Deduplicate: keep latest snapshot per stage so the sidebar doesn't fill
    # with dozens of "refinement" rows after multiple clarification cycles.
    # The full history is preserved in DB; only the display is deduplicated.
    seen: dict[str, dict] = {}
    for s in snaps:
        seen[s.stage] = {
            "id": s.id,
            "stage": s.stage,
            "langgraph_checkpoint_id": s.langgraph_checkpoint_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
    return {"checkpoints": list(seen.values())}


@router.get("/{session_id}/state")
async def get_state(session_id: str, db: DBSession = Depends(get_db)):
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        return {"state": None}
    return {"state": snap.snapshot_data, "stage": snap.stage}


@router.post("/{session_id}/execute")
async def execute_tests(session_id: str, db: DBSession = Depends(get_db)):
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found")

    generated = snap.snapshot_data.get("generated_tests", {})
    if not generated:
        raise HTTPException(status_code=422, detail="No generated tests to run")

    app_url = snap.snapshot_data.get("app_url", "https://www.saucedemo.com")
    ev.log_activity(session_id, "executor",
                    f"Running {len(generated)} test file(s) with pytest against {app_url}...")

    def _on_line(line: str) -> None:
        """Forward each pytest stdout line to the WebSocket as it arrives."""
        if line.strip():
            ev.broadcast(session_id, {"type": "execution_output", "line": line})

    # run_tests_streaming is blocking — run_in_threadpool keeps the event loop free
    # so WebSocket heartbeats and other requests continue to work during the test run.
    result = await run_in_threadpool(
        run_tests_streaming, generated, app_url, _on_line
    )

    exec_record = ExecutionResult(
        session_id=session_id,
        status=result["status"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        test_count=result["test_count"],
        pass_count=result["pass_count"],
        fail_count=result["fail_count"],
    )
    db.add(exec_record)

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if session:
        session.status = "completed" if result["status"] == "passed" else "error"
        session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(exec_record)

    level = "success" if result["status"] == "passed" else "error"
    ev.log_activity(session_id, "executor",
                    f"{result['pass_count']}/{result['test_count']} tests passed.", level)
    ev.broadcast(session_id, {"type": "execution_done", "result": result})
    return {"execution_id": exec_record.id, **result}


@router.get("/{session_id}/executions")
async def list_executions(session_id: str, db: DBSession = Depends(get_db)):
    results = (
        db.query(ExecutionResult)
        .filter(ExecutionResult.session_id == session_id)
        .order_by(ExecutionResult.created_at.desc())
        .all()
    )
    return {
        "results": [
            {
                "id": r.id,
                "status": r.status,
                "test_count": r.test_count,
                "pass_count": r.pass_count,
                "fail_count": r.fail_count,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ]
    }


# ── AI analysis endpoints ─────────────────────────────────────────────────────

class ExplainFailureRequest(BaseModel):
    test_name: str
    traceback: str
    test_case: dict | None = None  # optional TC spec with steps


@router.post("/{session_id}/explain-failure")
async def explain_failure(
    session_id: str,
    req: ExplainFailureRequest,
    db: DBSession = Depends(get_db),
):
    """Ask the LLM to explain why a test failed. Returns structured JSON (no markdown)."""
    _get_session_or_404(session_id, db)

    tc_block = ""
    if req.test_case:
        steps = req.test_case.get("steps", [])
        steps_text = "\n".join(
            f"  Step {i+1}: {s.get('action', '')} → {s.get('expected_result', '')}"
            for i, s in enumerate(steps)
        )
        tc_block = f"\nTest case spec:\n{steps_text}\n"

    prompt = (
        f"A Playwright/pytest test failed. Analyze the traceback and return a JSON object "
        f"with exactly these four keys — no markdown, no code fences, plain JSON only:\n\n"
        f"{{\n"
        f'  "failed_step": "one sentence — which step/line failed and what it was trying to do",\n'
        f'  "root_cause": "one sentence — the technical reason (stale locator, timing, wrong selector, etc.)",\n'
        f'  "fix": "one or two sentences — the concrete code change needed",\n'
        f'  "code_example": "optional short Python snippet showing the fix, or empty string"\n'
        f"}}\n\n"
        f"Test: {req.test_name}\n"
        f"{tc_block}"
        f"\nTraceback:\n{req.traceback}"
    )

    def _call_llm() -> str:
        llm = get_llm()
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = resp.content.strip()
        # Strip accidental fences
        raw = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\n?```\s*$', '', raw, flags=re.MULTILINE).strip()
        return raw

    raw_json = await run_in_threadpool(_call_llm)
    try:
        structured = json.loads(raw_json)
    except Exception:
        # Fallback: return as plain text in the failed_step field
        structured = {"failed_step": raw_json, "root_cause": "", "fix": "", "code_example": ""}
    return {"explanation": structured}


class ExecuteFileRequest(BaseModel):
    test_node: str  # e.g. "tests/test_cart.py" or "tests/test_cart.py::TestCart::test_add"


@router.post("/{session_id}/execute-file")
async def execute_single_test(
    session_id: str,
    req: ExecuteFileRequest,
    db: DBSession = Depends(get_db),
):
    """Run a single test file (or specific test node) instead of the full suite."""
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found")

    generated = snap.snapshot_data.get("generated_tests", {})
    if not generated:
        raise HTTPException(status_code=422, detail="No generated tests to run")

    app_url = snap.snapshot_data.get("app_url", "https://www.saucedemo.com")
    ev.log_activity(session_id, "executor", f"Running {req.test_node} against {app_url}...")

    def _on_line(line: str) -> None:
        if line.strip():
            ev.broadcast(session_id, {"type": "execution_output", "line": line})

    result = await run_in_threadpool(
        run_tests_streaming, generated, app_url, _on_line, req.test_node
    )

    exec_record = ExecutionResult(
        session_id=session_id,
        status=result["status"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        test_count=result["test_count"],
        pass_count=result["pass_count"],
        fail_count=result["fail_count"],
    )
    db.add(exec_record)
    db.commit()
    db.refresh(exec_record)

    level = "success" if result["status"] == "passed" else "error"
    ev.log_activity(session_id, "executor",
                    f"{result['pass_count']}/{result['test_count']} passed ({req.test_node}).", level)
    ev.broadcast(session_id, {"type": "execution_done", "result": result})
    return {"execution_id": exec_record.id, **result}


class RegenerateTestRequest(BaseModel):
    filename: str          # e.g. "tests/test_login.py"
    traceback: str         # failure traceback for context
    test_case: dict | None = None
    feedback: str | None = None   # optional user instruction: "what to fix"


@router.post("/{session_id}/regenerate-test")
async def regenerate_test(
    session_id: str,
    req: RegenerateTestRequest,
    db: DBSession = Depends(get_db),
):
    """Regenerate a single failing test file using the LLM."""
    _get_session_or_404(session_id, db)
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found")

    generated: dict[str, str] = snap.snapshot_data.get("generated_tests", {})
    original_code = generated.get(req.filename, "")
    if not original_code:
        raise HTTPException(status_code=404, detail=f"File '{req.filename}' not found in generated tests")

    app_url = snap.snapshot_data.get("app_url", "https://www.saucedemo.com")

    tc_block = ""
    if req.test_case:
        tc_block = f"\nTest case spec:\n{json.dumps(req.test_case, indent=2)}\n"

    # Put the fix guidance BEFORE the traceback so it's the first thing the LLM reads.
    feedback_block = f"\nFix guidance (apply this — highest priority):\n{req.feedback}\n" if req.feedback else ""

    prompt = (
        f"Fix the failing Playwright/pytest test file below.\n"
        f"Rewrite ONLY what is broken — keep all working tests, structure, and imports intact.\n\n"
        f"Application URL: {app_url}\n"
        f"{tc_block}"
        f"{feedback_block}"
        f"\nOriginal file ({req.filename}):\n```python\n{original_code}\n```\n\n"
        f"Failure traceback:\n{req.traceback}\n\n"
        f"Quality rules (match a senior engineer's standard):\n"
        f"- Semantic locators only: get_by_role/get_by_label/get_by_placeholder/get_by_text\n"
        f"- Full type hints on all methods and parameters\n"
        f"- Fluent page-chain: navigation methods return the next Page Object\n"
        f"- Method naming: click_x / fill_x / get_x / is_x / navigate\n"
        f"- Step tracking: print('▶ Step N: ...') before, print('✓ Step N done: ...') after\n"
        f"- Descriptive assertions: assert a == b, f'Step N: Expected {{b}}, got {{a}}'\n"
        f"- No vacuous passes: assert len(items) > 0 after .all(); guard while-loops\n"
        f"- No bare try/except that swallows failures\n"
        f"- URL from: os.environ.get('APP_URL', '{app_url}')\n"
        f"- Add __repr__ if the class doesn't have one\n\n"
        f"Return ONLY the fixed Python file content. No markdown fences. No explanation."
    )

    def _call_llm() -> str:
        llm = get_llm()
        resp = llm.invoke([HumanMessage(content=prompt)])
        return resp.content.strip()

    new_code = await run_in_threadpool(_call_llm)
    # Strip any accidental code fences
    new_code = re.sub(r'^```(?:python)?\s*\n?', '', new_code, flags=re.MULTILINE)
    new_code = re.sub(r'\n?```\s*$', '', new_code, flags=re.MULTILINE).strip()

    # Persist updated generated_tests in the latest snapshot
    new_generated = {**generated, req.filename: new_code}
    snap.snapshot_data = {**snap.snapshot_data, "generated_tests": new_generated}
    db.commit()

    # Push update to the LangGraph state so next run uses fixed code
    try:
        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": session_id}}
        graph.update_state(config, {"generated_tests": new_generated})
    except Exception:
        pass

    ev.broadcast(session_id, {
        "type": "stage_update",
        "stage": snap.snapshot_data.get("current_stage", "code_generation"),
        "state": snap.snapshot_data,
    })
    return {"filename": req.filename, "code": new_code}


# ── download / export endpoints ───────────────────────────────────────────────

@router.get("/{session_id}/download")
async def download_tests_zip(session_id: str, db: DBSession = Depends(get_db)):
    """Download all generated test files as a ZIP archive."""
    snap = _get_latest_snapshot(session_id, db)
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found")

    generated: dict[str, str] = snap.snapshot_data.get("generated_tests", {})
    if not generated:
        raise HTTPException(status_code=422, detail="No generated tests to download")

    # Import canonical templates (single source of truth)
    from backend.agents.test_generation_agent import _CONFTEST_TEMPLATE, _PYTEST_INI_TEMPLATE

    _FALLBACK_REQUIREMENTS = (
        "pytest>=8\n"
        "playwright\n"
        "pytest-timeout\n"
        "# After install run: playwright install chromium\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath, code in generated.items():
            zf.writestr(filepath, code)

        # conftest.py — use LLM-generated version if present (it may include
        # domain fixtures like logged_in_page); otherwise use the canonical template.
        if "conftest.py" not in generated:
            zf.writestr("conftest.py", _CONFTEST_TEMPLATE)

        # pytest.ini — use LLM-generated version if present; else canonical template.
        if "pytest.ini" not in generated:
            zf.writestr("pytest.ini", _PYTEST_INI_TEMPLATE)

        # requirements.txt — always the canonical version.
        zf.writestr("requirements.txt", _FALLBACK_REQUIREMENTS)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=testflow-tests-{session_id[:8]}.zip"},
    )


@router.get("/{session_id}/ci/github-actions")
async def download_github_actions(session_id: str, db: DBSession = Depends(get_db)):
    """Download a ready-to-use GitHub Actions workflow YAML."""
    session = _get_session_or_404(session_id, db)
    snap = _get_latest_snapshot(session_id, db)
    generated = snap.snapshot_data.get("generated_tests", {}) if snap else {}

    yaml_content = generate_github_actions_workflow(
        target_url=session.target_url or "https://www.saucedemo.com",
        test_files=list(generated.keys()),
        session_name=session.name,
    )
    return StreamingResponse(
        iter([yaml_content]),
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=tests.yml"},
    )


@router.get("/{session_id}/ci/azure-pipelines")
async def download_azure_pipelines(session_id: str, db: DBSession = Depends(get_db)):
    """Download a ready-to-use Azure Pipelines YAML."""
    session = _get_session_or_404(session_id, db)
    snap = _get_latest_snapshot(session_id, db)
    generated = snap.snapshot_data.get("generated_tests", {}) if snap else {}

    yaml_content = generate_azure_pipelines_yaml(
        target_url=session.target_url or "https://www.saucedemo.com",
        test_files=list(generated.keys()),
    )
    return StreamingResponse(
        iter([yaml_content]),
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=azure-pipelines.yml"},
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/{session_id}")
async def pipeline_websocket(websocket: WebSocket, session_id: str):
    """Receive real-time stage-change and activity log events."""
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    ev.register_queue(session_id, q)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        ev.unregister_queue(session_id, q)
