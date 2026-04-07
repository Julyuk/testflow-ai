"""
GitHub Actions workflow generator.

Produces a .github/workflows/tests.yml file tailored to the
generated test files from a TestFlow AI session.
"""


def generate_github_actions_workflow(
    target_url: str,
    test_files: list[str],
    session_name: str = "TestFlow AI Tests",
) -> str:
    """
    Generate a GitHub Actions workflow YAML for running Playwright pytest tests.

    Args:
        target_url: The application URL under test.
        test_files: List of generated test file paths (e.g. ['tests/test_login.py']).
        session_name: Human-readable name used in workflow name.

    Returns:
        YAML string for .github/workflows/tests.yml
    """
    test_paths = " ".join(
        f for f in test_files if f.startswith("tests/") or f.startswith("test_")
    ) or "tests/"

    workflow = f"""\
name: "{session_name}"

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]
  workflow_dispatch:

env:
  APP_URL: "{target_url}"

jobs:
  playwright-tests:
    name: Run Playwright Tests
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install pytest playwright pytest-playwright

      - name: Install Playwright browsers
        run: playwright install chromium --with-deps

      - name: Run tests
        run: pytest {test_paths} --tb=short -v
        env:
          BASE_URL: ${{{{ env.APP_URL }}}}

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: |
            .pytest_cache/
            test-results/
          retention-days: 7
"""
    return workflow


def generate_azure_pipelines_yaml(
    target_url: str,
    test_files: list[str],
) -> str:
    """Generate an azure-pipelines.yml for Azure DevOps."""
    test_paths = " ".join(
        f for f in test_files if f.startswith("tests/") or f.startswith("test_")
    ) or "tests/"

    return f"""\
trigger:
  - main
  - master

pool:
  vmImage: ubuntu-latest

variables:
  APP_URL: "{target_url}"

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.11"

  - script: pip install pytest playwright pytest-playwright
    displayName: Install dependencies

  - script: playwright install chromium --with-deps
    displayName: Install Playwright browsers

  - script: pytest {test_paths} --tb=short -v
    displayName: Run Playwright tests
    env:
      BASE_URL: $(APP_URL)

  - task: PublishTestResults@2
    condition: always()
    inputs:
      testResultsFormat: JUnit
      testResultsFiles: "**/test-results.xml"
"""
