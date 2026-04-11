# TestFlow AI — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                     USER (Browser)                       │
│              React 18 + TypeScript SPA                   │
│         Pipeline View │ Editors │ Code Viewer            │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + WebSocket
┌──────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend                        │
│   /api/sessions  │  /api/pipeline  │  /api/integrations  │
│                  WebSocket /ws/{id}                       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              LangGraph State Machine                      │
│                                                           │
│  intake → refinement ←──────────────────┐               │
│              │                           │               │
│         (questions?)                     │               │
│         ↓         ↓                      │               │
│  clarification  test_case_gen            │               │
│  _wait ──────→  │                        │               │
│  (user answers) ↓                        │               │
│              review_wait ←──────── (regenerate?)        │
│              (user approves)             │               │
│                  ↓                       │               │
│              code_gen                    │               │
│                  ↓                       │               │
│              validation ─── (errors?) ──┘               │
│                  ↓                                       │
│              export → END                                │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    PostgreSQL    MCP Servers   Azure DevOps
    (state +      (filesystem,  (test plans,
    checkpoints)   git, devops)  pipelines)
```

## Agent Responsibilities

| Agent | Input | Output | LLM Technique |
|-------|-------|--------|---------------|
| Requirements Agent | raw text | structured user stories + questions | Chain-of-thought + few-shot |
| Test Case Agent | structured requirements | test cases (Given/When/Then) | Technique prompting (EP, BVA) |
| Test Generation Agent | approved test cases | Python/Playwright code | Few-shot + POM template |
| Validation Agent | generated code | pass/fail + errors | AST parsing (no LLM) |

## Step-Back Navigation

Each pipeline stage creates a LangGraph checkpoint in PostgreSQL.
`GET /api/pipeline/{id}/checkpoints` returns the list.
`POST /api/pipeline/return-to-checkpoint` restores state and re-runs from there.

```
checkpoint_1 (after intake)
checkpoint_2 (after refinement)     ← user can restore here
checkpoint_3 (after test_case_gen)  ← or here
checkpoint_4 (after code_gen)
```

## State Schema

See `backend/agents/state.py` — `TestFlowState` TypedDict.
Key fields: `requirements`, `test_cases`, `generated_tests`,
`clarification_questions`, `stage_history`, `awaiting_human`.

## Data Flow

1. User submits requirements → `POST /api/pipeline/start`
2. Backend starts LangGraph graph with `thread_id = session_id`
3. Graph runs until first `interrupt()` (clarification or review)
4. Frontend receives stage update via WebSocket
5. User answers → `POST /api/pipeline/resume`
6. Graph continues to next interrupt or END
7. User can `GET /api/pipeline/{id}/checkpoints` and go back at any time
