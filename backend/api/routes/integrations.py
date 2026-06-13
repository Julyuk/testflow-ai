"""
Integration routes — Azure DevOps config + sync + MCP server management.

PAT tokens are encrypted at rest using Fernet (AES-128 symmetric encryption).
The encryption key is derived from settings.secret_key.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from backend.models.database import get_db
from backend.models.orm import IntegrationConfig
from backend.integrations.azure_devops import AzureDevOpsClient
from backend.integrations.github_integration import GitHubClient, validate_github_coords
from backend.config.settings import settings

router = APIRouter()

MCP_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "mcp_config.json"


# ── encryption helpers ────────────────────────────────────────────────────────

def _get_fernet():
    """Return a Fernet cipher derived from settings.secret_key."""
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception:
        return ""


# ── request / response schemas ────────────────────────────────────────────────

class AzureDevOpsConfigRequest(BaseModel):
    organization: str
    project: str
    pat: str


class AzureDevOpsSyncRequest(BaseModel):
    session_id: str
    test_plan_name: str = "TestFlow AI"


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict = {}


# ── Azure DevOps endpoints ────────────────────────────────────────────────────

@router.post("/azure-devops")
async def configure_azure_devops(
    config: AzureDevOpsConfigRequest,
    db: DBSession = Depends(get_db),
):
    """Save (or update) Azure DevOps credentials. PAT is stored encrypted."""
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "azure_devops"
    ).first()

    encrypted_pat = _encrypt(config.pat)

    if record:
        record.organization = config.organization
        record.project = config.project
        record.pat_encrypted = encrypted_pat
    else:
        record = IntegrationConfig(
            provider="azure_devops",
            organization=config.organization,
            project=config.project,
            pat_encrypted=encrypted_pat,
        )
        db.add(record)
    db.commit()
    return {"status": "configured", "organization": config.organization, "project": config.project}


@router.get("/azure-devops")
async def get_azure_devops_config(db: DBSession = Depends(get_db)):
    """Return stored Azure DevOps config (PAT masked)."""
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "azure_devops"
    ).first()
    if not record:
        return {"configured": False}
    return {
        "configured": True,
        "organization": record.organization,
        "project": record.project,
        "pat": "***" + (_decrypt(record.pat_encrypted)[-4:] if record.pat_encrypted else ""),
    }


@router.delete("/azure-devops")
async def delete_azure_devops_config(db: DBSession = Depends(get_db)):
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "azure_devops"
    ).first()
    if record:
        db.delete(record)
        db.commit()
    return {"status": "deleted"}


@router.post("/azure-devops/sync")
async def sync_to_azure_devops(req: AzureDevOpsSyncRequest, db: DBSession = Depends(get_db)):
    """Create a test plan + suite in Azure DevOps and sync all test cases."""
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "azure_devops"
    ).first()
    if not record:
        raise HTTPException(status_code=400, detail="Azure DevOps not configured")

    from backend.models.orm import StageSnapshot
    snap = (
        db.query(StageSnapshot)
        .filter(StageSnapshot.session_id == req.session_id)
        .order_by(StageSnapshot.created_at.desc())
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found for session")

    test_cases = snap.snapshot_data.get("test_cases", [])
    if not test_cases:
        raise HTTPException(status_code=422, detail="No test cases to sync")

    pat = _decrypt(record.pat_encrypted)
    client = AzureDevOpsClient(record.organization, record.project, pat)

    try:
        plan = await client.create_test_plan(req.test_plan_name)
        plan_id = plan["id"]

        suite = await client.create_test_suite(plan_id, "Automated Tests")
        suite_id = suite["id"]

        synced = 0
        for tc in test_cases:
            steps_html = client.test_case_to_steps_html(tc.get("steps", []))
            await client.create_test_case_work_item(tc.get("title", "Test"), steps_html)
            synced += 1

        return {
            "status": "synced",
            "plan_id": plan_id,
            "suite_id": suite_id,
            "test_cases_synced": synced,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure DevOps API error: {e}")


@router.post("/azure-devops/trigger-pipeline")
async def trigger_azure_pipeline(
    pipeline_id: int,
    branch: str = "main",
    db: DBSession = Depends(get_db),
):
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "azure_devops"
    ).first()
    if not record:
        raise HTTPException(status_code=400, detail="Azure DevOps not configured")

    pat = _decrypt(record.pat_encrypted)
    client = AzureDevOpsClient(record.organization, record.project, pat)
    try:
        result = await client.trigger_pipeline(pipeline_id, branch)
        return {"status": "triggered", "run": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure DevOps API error: {e}")


# ── GitHub endpoints ──────────────────────────────────────────────────────────

class GitHubConfigRequest(BaseModel):
    token: str
    owner: str
    repo: str
    branch: str = "main"


class GitHubPushRequest(BaseModel):
    session_id: str
    commit_message: str = "Add TestFlow AI generated tests"


@router.post("/github")
async def configure_github(
    config: GitHubConfigRequest,
    db: DBSession = Depends(get_db),
):
    """Save GitHub credentials. Token is stored encrypted."""
    try:
        validate_github_coords(config.owner, config.repo, config.branch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "github"
    ).first()

    encrypted_token = _encrypt(config.token)

    if record:
        record.organization = config.owner
        record.project = config.repo
        record.pat_encrypted = encrypted_token
        record.extra = {"branch": config.branch}
    else:
        record = IntegrationConfig(
            provider="github",
            organization=config.owner,
            project=config.repo,
            pat_encrypted=encrypted_token,
            extra={"branch": config.branch},
        )
        db.add(record)
    db.commit()
    return {"status": "configured", "owner": config.owner, "repo": config.repo}


@router.get("/github")
async def get_github_config(db: DBSession = Depends(get_db)):
    """Return stored GitHub config (token masked)."""
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "github"
    ).first()
    if not record:
        return {"configured": False}
    return {
        "configured": True,
        "owner": record.organization,
        "repo": record.project,
        "branch": (record.extra or {}).get("branch", "main"),
        "token": "***" + (_decrypt(record.pat_encrypted)[-4:] if record.pat_encrypted else ""),
    }


@router.delete("/github")
async def delete_github_config(db: DBSession = Depends(get_db)):
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "github"
    ).first()
    if record:
        db.delete(record)
        db.commit()
    return {"status": "deleted"}


@router.post("/github/push")
async def push_to_github(req: GitHubPushRequest, db: DBSession = Depends(get_db)):
    """Push all generated test files from the session to GitHub."""
    record = db.query(IntegrationConfig).filter(
        IntegrationConfig.provider == "github"
    ).first()
    if not record:
        raise HTTPException(status_code=400, detail="GitHub not configured")

    from backend.models.orm import StageSnapshot
    snap = (
        db.query(StageSnapshot)
        .filter(StageSnapshot.session_id == req.session_id)
        .order_by(StageSnapshot.created_at.desc())
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail="No pipeline state found for session")

    generated: dict[str, str] = snap.snapshot_data.get("generated_tests", {})
    if not generated:
        raise HTTPException(status_code=422, detail="No generated tests to push")

    token = _decrypt(record.pat_encrypted)
    branch = (record.extra or {}).get("branch", "main")
    client = GitHubClient(token, record.organization, record.project, branch)

    try:
        result = await client.push_files(generated, req.commit_message)
        if result["errors"]:
            raise HTTPException(
                status_code=502,
                detail=f"Push partially failed: {'; '.join(result['errors'])}",
            )
        return {
            "status": "pushed",
            "pushed_count": result["pushed_count"],
            "pushed": result["pushed"],
            "repo": f"{record.organization}/{record.project}",
            "branch": branch,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")


# ── MCP server endpoints ──────────────────────────────────────────────────────

@router.get("/mcp-servers")
async def list_mcp_servers():
    if not MCP_CONFIG_PATH.exists():
        return {"servers": []}
    with open(MCP_CONFIG_PATH) as f:
        config = json.load(f)
    servers = [
        {"name": name, "command": cfg.get("command", ""), "args": cfg.get("args", [])}
        for name, cfg in config.get("servers", {}).items()
    ]
    return {"servers": servers}


@router.post("/mcp-servers")
async def add_mcp_server(config: MCPServerConfig):
    existing: dict = {}
    if MCP_CONFIG_PATH.exists():
        with open(MCP_CONFIG_PATH) as f:
            existing = json.load(f)

    existing.setdefault("servers", {})[config.name] = {
        "command": config.command,
        "args": config.args,
        "env": config.env,
    }
    with open(MCP_CONFIG_PATH, "w") as f:
        json.dump(existing, f, indent=2)

    return {"status": "added", "server": config.name}


@router.delete("/mcp-servers/{name}")
async def remove_mcp_server(name: str):
    if not MCP_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    with open(MCP_CONFIG_PATH) as f:
        config = json.load(f)
    if name not in config.get("servers", {}):
        raise HTTPException(status_code=404, detail="Server not found")
    del config["servers"][name]
    with open(MCP_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    return {"status": "removed"}
