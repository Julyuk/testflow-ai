"""Session CRUD routes — PostgreSQL-backed."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from backend.models.database import get_db
from backend.models.orm import Session as SessionModel

router = APIRouter()


# ── request / response schemas ────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: str
    description: str = ""
    target_url: str = "https://www.saucedemo.com"


class SessionResponse(BaseModel):
    id: str
    name: str
    description: str
    target_url: str
    status: str
    current_stage: str
    created_at: str

    class Config:
        from_attributes = True


def _to_response(s: SessionModel) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description or "",
        "target_url": s.target_url or "",
        "status": s.status,
        "current_stage": s.current_stage,
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=SessionResponse, status_code=201)
async def create_session(req: CreateSessionRequest, db: DBSession = Depends(get_db)):
    session = SessionModel(
        name=req.name,
        description=req.description,
        target_url=req.target_url,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _to_response(session)


@router.get("/", response_model=list[SessionResponse])
async def list_sessions(db: DBSession = Depends(get_db)):
    sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
    return [_to_response(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_response(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
