"""
Azure DevOps integration service.

Creates test plans, test suites, syncs test cases,
and triggers CI/CD pipelines.
"""

import httpx
from base64 import b64encode
from typing import Optional


class AzureDevOpsClient:
    def __init__(self, organization: str, project: str, pat: str):
        self.base_url = f"https://dev.azure.com/{organization}/{project}"
        token = b64encode(f":{pat}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    async def create_test_plan(self, name: str) -> dict:
        url = f"{self.base_url}/_apis/test/plans?api-version=7.1"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers, json={"name": name})
            resp.raise_for_status()
            return resp.json()

    async def create_test_suite(self, plan_id: int, name: str) -> dict:
        url = f"{self.base_url}/_apis/test/plans/{plan_id}/suites?api-version=7.1"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers,
                                     json={"suiteType": "staticTestSuite", "name": name})
            resp.raise_for_status()
            return resp.json()

    async def create_test_case_work_item(self, title: str, steps_html: str) -> dict:
        url = f"{self.base_url}/_apis/wit/workitems/$Test%20Case?api-version=7.1"
        body = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps", "value": steps_html},
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers={**self.headers, "Content-Type": "application/json-patch+json"},
                json=body
            )
            resp.raise_for_status()
            return resp.json()

    async def trigger_pipeline(self, pipeline_id: int, branch: str = "main") -> dict:
        url = f"{self.base_url}/_apis/pipelines/{pipeline_id}/runs?api-version=7.1"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers,
                                     json={"resources": {"repositories": {"self": {"refName": f"refs/heads/{branch}"}}}})
            resp.raise_for_status()
            return resp.json()

    def test_case_to_steps_html(self, steps: list[dict]) -> str:
        """Convert test steps to Azure DevOps steps HTML format."""
        rows = ""
        for i, step in enumerate(steps, 1):
            rows += (
                f'<step id="{i}" type="ActionStep">'
                f'<parameterizedString isformatted="true">{step["action"]}</parameterizedString>'
                f'<parameterizedString isformatted="true">{step["expected_result"]}</parameterizedString>'
                f'</step>'
            )
        return f"<steps id='0' last='{len(steps)}'>{rows}</steps>"
