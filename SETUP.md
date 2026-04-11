# TestFlow AI — Setup Guide

## 1. LLM API Key

TestFlow AI supports **OpenAI** and **Anthropic** as LLM providers. You need an API key for whichever you choose.

### OpenAI (recommended default)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key
3. Set in `.env`:
   ```
   LLM_PROVIDER=openai
   LLM_MODEL=gpt-4o
   OPENAI_API_KEY=sk-...
   ```

### Anthropic

1. Go to [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key
2. Set in `.env`:
   ```
   LLM_PROVIDER=anthropic
   LLM_MODEL=claude-sonnet-4-5
   ANTHROPIC_API_KEY=sk-ant-...
   ```

### Cost estimate

Each full pipeline run (requirements → test cases → code generation) makes 3–4 LLM calls:

| Stage | Approx tokens |
|-------|--------------|
| Requirements refinement | ~2 000 input / 500 output |
| Test case generation | ~4 000 / 2 000 |
| Code generation | ~6 000 / 3 000 |
| Validation retry (if triggered) | ~2 000 / 500 |

**Total per run: ~14 000–20 000 tokens → roughly $0.10–0.20** at current GPT-4o pricing.

Set a monthly spending limit on your provider's console to avoid surprises.

---

## 2. Database

By default, the Docker Compose setup starts a PostgreSQL 16 container. No configuration needed.

For a custom PostgreSQL instance set:
```
DATABASE_URL=postgresql://user:password@host:5432/testflow
```

The ORM creates tables automatically on first startup.

---

## 3. Running with Docker (recommended)

```bash
# 1. Copy and fill the env file
cp .env.example .env
# Edit .env: set LLM_PROVIDER, API key, SECRET_KEY

# 2. Start all services
docker compose up

# 3. Open
#    Frontend:  http://localhost:5173
#    API docs:  http://localhost:8000/docs
```

To rebuild after code changes:
```bash
docker compose build && docker compose up
```

---

## 4. Running locally

**Prerequisites:** Python 3.11+, Node.js 20+, PostgreSQL 16 running locally.

```bash
cp .env.example .env
# Edit .env: set DATABASE_URL to your local Postgres, add API key

# Backend
pip install -r backend/requirements.txt
uvicorn backend.api.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Or use the helper script:
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

---

## 5. Azure DevOps integration (optional)

After startup, go to **Settings** in the app and enter:

- **Organization** — your Azure DevOps org name
- **Project** — project where test plans will be created
- **Personal Access Token** — PAT with scopes: *Work Items (Read & Write)*, *Test Plans (Read & Write)*

The PAT is encrypted with AES-128 before storage. Once configured:
- Test cases can be synced as Work Items in Azure Test Plans
- Azure Pipelines can be triggered from the Code Generation view
- A ready-made `azure-pipelines.yml` can be downloaded

---

## 6. Pre-flight checklist

- [ ] `.env` file exists and is populated (copy from `.env.example`)
- [ ] `LLM_PROVIDER` and the matching API key are set
- [ ] `SECRET_KEY` is set to a random 32+ character string
- [ ] PostgreSQL is reachable (Docker Compose handles this automatically)
- [ ] Frontend dev server is running on port 5173
- [ ] Backend is running on port 8000
- [ ] `http://localhost:5173` loads the session list page
- [ ] (Optional) Azure DevOps credentials entered in the Settings page

---

## 7. Common issues

**Pipeline hangs after "Start Pipeline"**
- Check backend logs: `docker compose logs backend -f`
- Verify the API key is valid and has sufficient quota

**`DATABASE_URL` connection refused**
- If running locally (not Docker), make sure PostgreSQL is started and the URL is correct
- Default Docker URL: `postgresql://testflow:testflow@db:5432/testflow`

**Frontend shows blank page**
- Run `npm install` inside `frontend/` if you skipped it
- Check browser console for errors; the Vite dev server proxies `/api` and `/ws` to the backend

**Tests fail with Playwright browser error**
- Inside Docker the backend container installs Chromium automatically via `playwright install`
- For local runs: `playwright install chromium`
