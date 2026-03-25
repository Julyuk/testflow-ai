"""
Requirements Refinement Agent.

Receives raw free-text requirements, detects ambiguities,
returns structured requirements in User Story format
or a list of clarifying questions.
"""

import json
import re
import uuid
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output (handles all variants)."""
    text = text.strip()
    m = re.match(r'^```(?:json)?\s*\n?(.*?)\n?```\s*$', text, re.DOTALL)
    return m.group(1).strip() if m else text

from backend.agents.state import TestFlowState, Requirement, RequirementStatus, PipelineStage
from backend.config.llm import get_llm


SYSTEM_PROMPT = """\
You are a senior QA analyst specializing in requirements analysis.

Your task:
1. Split the input into INDIVIDUAL requirements — one per line, bullet, or sentence.
   Each distinct feature, behaviour, or test scenario must become its own entry in "structured".
   NEVER merge multiple requirements into a single entry.
2. For each individual requirement, check if it clearly specifies:
   - WHO performs the action (actor/role)
   - WHAT action is performed
   - WHAT the expected result is
3. Only mark a requirement as ambiguous (ambiguous: true) if critical information
   is genuinely missing and cannot be reasonably inferred.
   If a requirement is clear enough to generate meaningful test cases, mark it ambiguous: false.
4. For clear requirements, convert them to User Story format:
   "As a [role], I want to [action], so that [value]"
   and add 2-3 acceptance criteria in Given/When/Then format.
5. Collect specific clarifying questions ONLY for truly ambiguous items.
   If all requirements are clear, return an empty "questions" list.

Output JSON only. No explanation text outside JSON.

Example input:
"Login should fail when wrong password is entered and show an error message
User should be able to add a product to the shopping cart"

Example output:
{
  "structured": [
    {
      "id": "REQ-001",
      "raw_text": "Login should fail when wrong password is entered and show an error message",
      "user_story": "As a registered user, I want to see an error message when I enter the wrong password, so that I know my login attempt failed",
      "acceptance_criteria": [
        "Given a registered user, When wrong password is submitted, Then an error message is displayed",
        "Given a registered user, When wrong password is submitted, Then the user remains on the login page",
        "Given a registered user, When wrong password is submitted, Then the password field is cleared"
      ],
      "ambiguous": false
    },
    {
      "id": "REQ-002",
      "raw_text": "User should be able to add a product to the shopping cart",
      "user_story": "As a shopper, I want to add a product to my shopping cart, so that I can purchase it later",
      "acceptance_criteria": [
        "Given a product page, When the user clicks Add to Cart, Then the product appears in the cart",
        "Given a product page, When the user clicks Add to Cart, Then the cart item count increases by 1",
        "Given a product already in the cart, When the user adds it again, Then the quantity is incremented"
      ],
      "ambiguous": false
    }
  ],
  "questions": []
}
"""


class RefinementOutput(BaseModel):
    structured: list[dict] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


def run_requirements_agent(state: TestFlowState) -> dict:
    llm = get_llm()

    # Use clarification answers if available
    context = state["raw_requirements"]
    raw_answers = state.get("clarification_answers") or {}
    # The frontend wraps answers in { "answers": { "Q text": "A text" } }
    # Unwrap that envelope so we get a flat {question: answer} dict.
    if "answers" in raw_answers and isinstance(raw_answers["answers"], dict):
        raw_answers = raw_answers["answers"]
    # Only include non-empty answers (user may have skipped clarification)
    filled_answers = {q: a for q, a in raw_answers.items() if a and a.strip()}
    if filled_answers:
        answers_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in filled_answers.items())
        context += f"\n\nClarification answers:\n{answers_text}"

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Requirements to analyze:\n\n{context}"),
    ]

    response = llm.invoke(messages)
    raw = _strip_fences(response.content)

    try:
        output = RefinementOutput(**json.loads(raw))
    except Exception:
        # Fallback: split by non-empty lines so each line becomes its own requirement
        lines = [l.strip() for l in context.splitlines() if l.strip()]
        if not lines:
            lines = [context.strip()]
        fallback_structured = [
            {
                "id": f"REQ-{str(i + 1).zfill(3)}",
                "raw_text": line,
                "user_story": line,
                "acceptance_criteria": [],
                "ambiguous": False,
            }
            for i, line in enumerate(lines)
        ]
        output = RefinementOutput(structured=fallback_structured, questions=[])

    requirements = [
        Requirement(
            id=r.get("id", f"REQ-{uuid.uuid4().hex[:4].upper()}"),
            raw_text=r.get("raw_text", ""),
            user_story=r.get("user_story"),
            acceptance_criteria=r.get("acceptance_criteria", []),
            status=RequirementStatus.STRUCTURED if not r.get("ambiguous") else RequirementStatus.RAW,
        ).model_dump()
        for r in output.structured
    ]

    if output.questions:
        update: dict[str, Any] = {
            "requirements": requirements,
            "current_stage": PipelineStage.CLARIFICATION_WAIT,
            "clarification_questions": output.questions,
            "awaiting_human": True,
        }
    else:
        # No clarification needed — go straight to requirements review.
        # Set awaiting_human=True and stage=REQUIREMENTS_REVIEW here so the
        # broadcast from _run_pipeline reaches the UI *before* the interrupt()
        # call inside requirements_review_node suspends the graph.
        update: dict[str, Any] = {
            "requirements": requirements,
            "current_stage": PipelineStage.REQUIREMENTS_REVIEW,
            "clarification_questions": [],
            "awaiting_human": True,
        }

    return update
