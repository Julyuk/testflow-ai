"""
Core state schema for the TestFlow AI LangGraph pipeline.
All agents read from and write to this state.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    INTAKE = "intake"
    REFINEMENT = "refinement"
    CLARIFICATION_WAIT = "clarification_wait"
    REQUIREMENTS_REVIEW = "requirements_review"
    TEST_CASE_GENERATION = "test_case_generation"
    REVIEW_WAIT = "review_wait"
    CODE_GENERATION = "code_generation"
    VALIDATION = "validation"
    EXPORT = "export"
    COMPLETED = "completed"
    ERROR = "error"


class RequirementStatus(str, Enum):
    RAW = "raw"
    STRUCTURED = "structured"
    APPROVED = "approved"


class TestCaseType(str, Enum):
    HAPPY_PATH = "happy_path"
    NEGATIVE = "negative"
    EDGE_CASE = "edge_case"
    SECURITY = "security"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestStep(BaseModel):
    action: str
    expected_result: str


class Requirement(BaseModel):
    id: str
    raw_text: str
    user_story: Optional[str] = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: RequirementStatus = RequirementStatus.RAW


class TestCase(BaseModel):
    id: str
    title: str
    requirement_id: str
    type: TestCaseType
    priority: Priority
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    approved: bool = False


class ValidationResult(BaseModel):
    filename: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StageSnapshot(BaseModel):
    stage: PipelineStage
    snapshot_data: dict  # serialized state at this point
    timestamp: str


class TestFlowState(TypedDict):
    session_id: str
    user_id: str

    # Requirements
    raw_requirements: str
    requirements: list[dict]  # list[Requirement] serialized

    # Clarification
    clarification_questions: list[str]
    clarification_answers: dict

    # Test Cases
    test_cases: list[dict]  # list[TestCase] serialized

    # Generated Code
    generated_tests: dict  # filename -> code str

    # Validation
    validation_results: list[dict]

    # Pipeline Control
    current_stage: str
    stage_history: list[dict]  # list[StageSnapshot] serialized
    iteration_count: int

    # Human-in-the-loop
    awaiting_human: bool
    user_feedback: Optional[str]

    # Target application
    app_url: str

    # Error handling
    error: Optional[str]
    retry_count: int
