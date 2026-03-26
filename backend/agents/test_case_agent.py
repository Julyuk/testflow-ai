"""
Test Case Generation Agent.

Receives structured requirements and generates comprehensive test cases
using test design techniques: EP, BVA, Decision Table, State Transition.
"""

import json
import re
import uuid

from langchain_core.messages import SystemMessage, HumanMessage


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output (handles all variants)."""
    text = text.strip()
    m = re.match(r'^```(?:json)?\s*\n?(.*?)\n?```\s*$', text, re.DOTALL)
    return m.group(1).strip() if m else text

from backend.agents.state import TestFlowState, TestCase, TestCaseType, Priority, TestStep, PipelineStage
from backend.config.llm import get_llm


SYSTEM_PROMPT = """\
You are a senior QA engineer expert in test case design.

For each requirement provided, generate a comprehensive set of test cases.
Apply these test design techniques:
- Equivalence Partitioning (EP): valid and invalid equivalence classes
- Boundary Value Analysis (BVA): boundary values for numeric/string inputs
- Decision Table: combinations of conditions
- State Transition: different states of the system

For EACH requirement generate at minimum:
- 1-2 happy path test cases
- 1-2 negative test cases
- 1 edge/boundary case

Return JSON array of test cases. Each test case:
{
  "id": "TC-XXX",
  "title": "Descriptive title",
  "requirement_id": "REQ-XXX",
  "type": "happy_path|negative|edge_case|security",
  "priority": "critical|high|medium|low",
  "preconditions": ["condition 1", "condition 2"],
  "steps": [
    {"action": "Navigate to login page", "expected_result": "Login form is displayed"}
  ],
  "tags": ["auth", "login"]
}

Output ONLY a JSON array. No markdown, no explanation.
"""


def run_test_case_agent(state: TestFlowState) -> dict:
    llm = get_llm()

    requirements_text = json.dumps(state["requirements"], ensure_ascii=False, indent=2)

    user_feedback = state.get("user_feedback", "")
    feedback_context = f"\n\nUser feedback for this regeneration: {user_feedback}" if user_feedback and user_feedback != "regenerate" else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Generate test cases for these requirements:\n\n{requirements_text}{feedback_context}"),
    ]

    response = llm.invoke(messages)
    raw = _strip_fences(response.content)

    try:
        raw_cases = json.loads(raw)
    except Exception:
        raw_cases = []

    test_cases = []
    for idx, tc in enumerate(raw_cases, 1):
        try:
            steps = [
                TestStep(
                    action=s.get("action", ""),
                    expected_result=s.get("expected_result", ""),
                ).model_dump()
                for s in tc.get("steps", [])
            ]
            test_case = TestCase(
                id=tc.get("id", f"TC-{idx:03d}"),
                title=tc.get("title", f"Test case {idx}"),
                requirement_id=tc.get("requirement_id", "REQ-001"),
                type=tc.get("type", TestCaseType.HAPPY_PATH),
                priority=tc.get("priority", Priority.MEDIUM),
                preconditions=tc.get("preconditions", []),
                steps=steps,
                tags=tc.get("tags", []),
                approved=False,
            )
            test_cases.append(test_case.model_dump())
        except Exception:
            continue

    return {
        "test_cases": test_cases,
        "current_stage": PipelineStage.REVIEW_WAIT,
        "awaiting_human": True,
    }
