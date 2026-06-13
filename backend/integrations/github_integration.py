"""
GitHub integration — pushes generated test files to a GitHub repository
via the GitHub REST API (no git CLI dependency).

Requires a Personal Access Token with Contents: Read & Write scope.
"""

import base64
import re
from typing import Optional

import httpx

# GitHub enforces these constraints server-side; we validate early for
# clear error messages and to prevent path-traversal in URL construction.
_OWNER_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$')
_REPO_RE  = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
_BRANCH_RE = re.compile(r'^[A-Za-z0-9._/\-]{1,255}$')


def validate_github_coords(owner: str, repo: str, branch: str) -> None:
    """Raise ValueError if any coordinate fails the allowed-character check."""
    if not _OWNER_RE.match(owner):
        raise ValueError(f"Invalid GitHub owner: {owner!r}")
    if not _REPO_RE.match(repo):
        raise ValueError(f"Invalid GitHub repo: {repo!r}")
    if not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")


class GitHubClient:
    _API_BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str, repo: str, branch: str = "main"):
        validate_github_coords(owner, repo, branch)
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, path: str) -> str:
        return f"{self._API_BASE}/repos/{self.owner}/{self.repo}{path}"

    async def _get_file_sha(self, client: httpx.AsyncClient, path: str) -> Optional[str]:
        """Return the blob SHA of an existing file, or None if it doesn't exist."""
        resp = await client.get(
            self._repo_url(f"/contents/{path}"),
            headers=self._headers,
            params={"ref": self.branch},
        )
        if resp.status_code == 200:
            return resp.json().get("sha")
        return None

    async def push_files(
        self,
        files: dict[str, str],
        commit_message: str = "Add TestFlow AI generated tests",
    ) -> dict:
        """
        Create or update files in the repository.

        Args:
            files: mapping of repo-relative path → file content (plain text).
            commit_message: git commit message.

        Returns:
            dict with pushed_count and any per-file errors.
        """
        pushed: list[str] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for path, content in files.items():
                encoded = base64.b64encode(content.encode()).decode()
                sha = await self._get_file_sha(client, path)
                body: dict = {
                    "message": commit_message,
                    "content": encoded,
                    "branch": self.branch,
                }
                if sha:
                    body["sha"] = sha

                resp = await client.put(
                    self._repo_url(f"/contents/{path}"),
                    headers=self._headers,
                    json=body,
                )
                if resp.status_code in (200, 201):
                    pushed.append(path)
                else:
                    errors.append(f"{path}: {resp.status_code} {resp.text[:120]}")

        return {"pushed_count": len(pushed), "pushed": pushed, "errors": errors}

    async def verify_connection(self) -> bool:
        """Return True if the token can read the target repository."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                self._repo_url(""),
                headers=self._headers,
            )
            return resp.status_code == 200
