"""SQLAlchemy ORM models for TestFlow AI."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, ForeignKey, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.database import Base


def _uuid():
    return str(uuid.uuid4())


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    target_url = Column(Text, default="https://www.saucedemo.com")
    status = Column(String(50), default="created")   # created|running|paused|completed|error
    current_stage = Column(String(100), default="intake")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshots = relationship(
        "StageSnapshot", back_populates="session",
        cascade="all, delete-orphan", order_by="StageSnapshot.created_at"
    )
    execution_results = relationship(
        "ExecutionResult", back_populates="session",
        cascade="all, delete-orphan", order_by="ExecutionResult.created_at"
    )


class StageSnapshot(Base):
    """One row per pipeline stage completion. Mirrors LangGraph checkpoints
    in a human-readable form and stores the checkpoint_id needed for restore."""

    __tablename__ = "stage_snapshots"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    session_id = Column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    stage = Column(String(100), nullable=False)
    snapshot_data = Column(JSON, nullable=False, default=dict)
    langgraph_checkpoint_id = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="snapshots")


class ExecutionResult(Base):
    """Results from running pytest/Playwright against the generated tests."""

    __tablename__ = "execution_results"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    session_id = Column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    status = Column(String(50), default="running")   # running|passed|failed|error
    stdout = Column(Text, default="")
    stderr = Column(Text, default="")
    test_count = Column(Integer, default=0)
    pass_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="execution_results")


class IntegrationConfig(Base):
    """Stores encrypted integration credentials (Azure DevOps, etc.)."""

    __tablename__ = "integration_configs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    provider = Column(String(50), nullable=False, unique=True)  # "azure_devops"
    organization = Column(Text, default="")
    project = Column(Text, default="")
    pat_encrypted = Column(Text, default="")   # Fernet-encrypted PAT
    extra = Column(JSON, default=dict)          # additional provider-specific fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
