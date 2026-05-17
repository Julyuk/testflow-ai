# TestFlow AI

AI-powered multi-agent framework for automated web application testing. Accepts plain-English testing requirements and drives the full lifecycle — requirements structuring, test case generation, Playwright code generation, and CI/CD export — with a human checkpoint at every critical stage.

---

## How It Works

```
Requirements (plain text)
        │
        ▼
 Requirements Agent  ──→  User Stories + Acceptance Criteria
        │
        ▼
 Clarification? ──→ (optional) AI asks follow-up questions
        │
        ▼
 Test Case Agent  ──→  Test cases (EP / BVA / Decision Table / State Transition)
        │                         ⏸ Human review & approval
        ▼
 Code Generation Agent  ──→  Python / Playwright (Page Object Model)
        │
        ▼
 Validation Agent  ──→  AST syntax check (no LLM)
        │
        ▼
 Export  ──→  ZIP / GitHub Actions workflow / Azure Pipelines YAML
```

At any stage you can click **"Restore"** in the sidebar to roll back to a previous checkpoint and re-run the pipeline from that point. Every stage is persisted in PostgreSQL via LangGraph checkpoints.

---

## Features

- **Natural language input** — describe what to test in plain English; no structured format required
- **Requirements structuring** — each requirement is converted to a User Story with Given/When/Then acceptance criteria
- **Multi-technique test case generation** — Equivalence Partitioning, Boundary Value Analysis, Decision Tables, State Transitions; covers happy path, negative, edge case, and security scenarios
- **Page Object Model code generation** — generates a full pytest + Playwright project with separate page classes and test files
- **Human-in-the-loop checkpoints** — pipeline pauses at Requirements Review and Test Case Review for user approval and editing
- **Backtracking** — roll back to any completed stage and re-run forward; all checkpoints are durable (PostgreSQL)
- **Real-time agent activity** — all agent events are streamed to the browser via WebSocket
- **Azure DevOps integration** — sync test cases as Work Items in Azure Test Plans; trigger pipelines from the UI
- **GitHub Actions export** — download a ready-to-use `.github/workflows/tests.yml`
- **In-app test runner** — run generated tests directly from the UI; results displayed with per-test pass/fail status

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph 1.x (state graph + PostgreSQL checkpoints) |
| LLM | OpenAI GPT-4o or Anthropic (configurable via `.env`) |
| Backend | FastAPI + SQLAlchemy + PostgreSQL |
| Frontend | React 18 + TypeScript + Ant Design 5 + Zustand |
| Real-time | WebSocket (agent events pushed to UI) |
| Test runner | pytest + Playwright (Python) |
| Containers | Docker Compose |

---

## Quick Start (Docker)

**Prerequisites:** Docker, Docker Compose, an OpenAI or Anthropic API key.

```bash
git clone https://github.com/Julyuk/testflow-ai.git
cd testflow-ai

cp .env.example .env
# Open .env and set your API key:
#   LLM_PROVIDER=openai   (or anthropic)
#   OPENAI_API_KEY=sk-...  (or ANTHROPIC_API_KEY=sk-ant-...)

docker compose up
```

Open **http://localhost:5173**

Backend API docs: **http://localhost:8000/docs**

---

## Quick Start (Local)

**Prerequisites:** Python 3.11+, Node.js 20+, PostgreSQL 16.

```bash
git clone https://github.com/Julyuk/testflow-ai.git
cd testflow-ai

# 1. Backend
cp .env.example .env          # fill in API key and DATABASE_URL
cd backend
pip install -r requirements.txt
cd ..
uvicorn backend.api.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

See [SETUP.md](SETUP.md) for a full checklist including Azure DevOps configuration.

---

## Project Structure

```
testflow-ai/
├── backend/
│   ├── agents/
│   │   ├── state.py                 # LangGraph state schema + enums
│   │   ├── orchestrator.py          # State machine definition + routing
│   │   ├── requirements_agent.py    # LLM: text → User Stories
│   │   ├── test_case_agent.py       # LLM: User Stories → test cases
│   │   ├── test_generation_agent.py # LLM: test cases → Playwright code
│   │   └── validation_agent.py      # AST syntax check (no LLM)
│   ├── api/
│   │   ├── main.py                  # FastAPI app entry point
│   │   └── routes/
│   │       ├── sessions.py          # Session CRUD
│   │       ├── pipeline.py          # Pipeline start/resume/backtrack + WebSocket
│   │       └── integrations.py      # Azure DevOps, GitHub Actions endpoints
│   ├── config/
│   │   ├── settings.py              # Pydantic settings (loaded from .env)
│   │   └── llm.py                   # LLM client factory (OpenAI / Anthropic)
│   ├── integrations/
│   │   ├── azure_devops.py          # Azure DevOps REST API client
│   │   └── mcp_client.py            # MCP server integration
│   ├── models/
│   │   ├── database.py              # SQLAlchemy engine + session
│   │   └── orm.py                   # ORM models: Session, StageSnapshot, ExecutionResult
│   ├── runner/
│   │   └── executor.py              # subprocess pytest runner + result parser
│   ├── ci/
│   │   └── github_actions.py        # GitHub Actions YAML generator
│   ├── events.py                    # WebSocket event broadcaster
│   ├── tests/                       # pytest test suite (60 tests)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/                   # HomePage, PipelinePage, SettingsPage
│       ├── components/
│       │   ├── pipeline/            # PipelineView, StageCard
│       │   ├── editors/             # RequirementsEditor, TestCaseEditor,
│       │   │                        #   ClarificationPanel, CodeViewer
│       │   └── common/              # Layout, AgentActivityLog
│       ├── hooks/                   # useWebSocket, useSession
│       ├── store/                   # Zustand: sessionStore
│       ├── api/                     # axios client
│       └── types/                   # TypeScript interfaces
├── ci/
│   ├── github-actions.yml           # Template: GitHub Actions workflow
│   └── azure-pipelines.yml          # Template: Azure Pipelines
├── docs/
│   └── ARCHITECTURE.md
├── scripts/
│   └── start.sh                     # Local dev startup script
├── docker-compose.yml
├── .env.example
└── pytest.ini
```

---

## Pipeline Stages

| # | Stage | Waits for human? | Description |
|---|-------|-----------------|-------------|
| 1 | Intake | — | User pastes requirements |
| 2 | Analysis | — | LLM structures text into User Stories |
| 3 | Clarification | If needed | LLM asks follow-up questions; user answers or skips |
| 4 | Req. Review | **Yes** | User reviews, edits, and approves structured requirements |
| 5 | TC Generation | — | LLM generates test cases |
| 6 | TC Review | **Yes** | User selects and approves test cases for code generation |
| 7 | Code Gen | — | LLM writes Python/Playwright code (Page Object Model) |
| 8 | Validation | — | AST + import check; auto-retries code gen up to 3× |
| 9 | Export | — | Artifacts ready for download or CI/CD push |

---

## Running the Test Suite

```bash
PYTHONPATH=. pytest backend/tests/ -v
# Expected: 60 passed
```

Test files:
- `test_sessions_api.py` — session CRUD endpoints
- `test_pipeline_api.py` — pipeline start, resume, backtrack, edit
- `test_stage_transitions.py` — LangGraph routing + graph structure
- `test_validation_agent.py` — AST validation cases
- `test_executor.py` — pytest runner and result parsing

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_PROVIDER` | Yes | `openai` or `anthropic` |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `ANTHROPIC_API_KEY` | If using Anthropic | Anthropic API key |
| `LLM_MODEL` | No | Model name (default: `gpt-4o` for OpenAI) |
| `DATABASE_URL` | No | PostgreSQL URL (default: Docker service) |
| `SECRET_KEY` | Yes | Random 32+ char string for session encryption |
| `FRONTEND_URL` | No | CORS origin (default: `http://localhost:5173`) |
| `AZURE_DEVOPS_ORG` | No | Azure DevOps organization name |
| `AZURE_DEVOPS_PAT` | No | Azure DevOps Personal Access Token |

---

© 2026 Yuliia Ukrainets. All rights reserved. Unauthorized use, copying or distribution is prohibited.
