"""
Validation Agent.

Validates generated Python/Playwright test code:
1. AST syntax check
2. Required imports check
3. Basic pytest convention check (test_ prefix)
4. Pylint static analysis (errors + warnings)

On failure: returns errors so the orchestrator routes back to code_gen.
"""

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.agents.state import TestFlowState, ValidationResult, PipelineStage

# Only playwright is a hard import requirement.
# pytest is the test runner — test files often rely on conftest.py fixtures
# without explicitly importing pytest, so requiring it produces false warnings.
REQUIRED_IMPORTS = {"playwright"}

# Pylint message-id pattern: letter followed by 4 digits, e.g. E0001, W0611
# The category is the first letter of the message-id.
_PYLINT_MSG_RE = re.compile(r'\b([EWRCIF])\d{4}\b')

PYLINT_ERROR_CATEGORIES = {"E", "F"}   # Error, Fatal
PYLINT_WARN_CATEGORIES  = {"W"}        # Warning


def _run_pylint(filename: str, code: str) -> tuple[list[str], list[str]]:
    """Run pylint on code string. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            [
                sys.executable, "-m", "pylint",
                tmp_path,
                "--output-format=text",
                "--score=no",
                "--disable=C,R,W0611,W0401",   # suppress convention, refactor, unused-import
                "--max-line-length=120",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in result.stdout.splitlines():
            # Pylint text format: path:line:col: MXXXX (message-type) description
            # Extract the message-id (e.g. E0001) to determine category reliably.
            m = _PYLINT_MSG_RE.search(line)
            if m:
                category = m.group(1)
                msg = line.strip()
                if category in PYLINT_ERROR_CATEGORIES:
                    errors.append(f"pylint [{filename}]: {msg}")
                elif category in PYLINT_WARN_CATEGORIES:
                    warnings.append(f"pylint [{filename}]: {msg}")
    except Exception as e:
        warnings.append(f"pylint unavailable: {e}")
    finally:
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
    return errors, warnings


def _check_code(filename: str, code: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. AST syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return ValidationResult(filename=filename, passed=False, errors=errors).model_dump()

    # 2. Import check
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    missing = REQUIRED_IMPORTS - imported_modules
    if missing:
        warnings.append(f"Missing expected imports: {', '.join(missing)}")

    # 3. Test function check (only for files that should contain test functions)
    if _is_test_file(filename):
        test_funcs = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        if not test_funcs:
            errors.append("No test functions found (expected functions starting with 'test_')")

    # 4. Pylint static analysis
    pylint_errors, pylint_warnings = _run_pylint(filename, code)
    errors.extend(pylint_errors)
    warnings.extend(pylint_warnings)

    passed = len(errors) == 0
    return ValidationResult(
        filename=filename,
        passed=passed,
        errors=errors,
        warnings=warnings,
    ).model_dump()


# Files that live in tests/ but are data/helper modules, not test suites.
# They start with test_ (pytest naming convention) but contain no test functions.
_DATA_MODULE_NAMES = {"test_data.py", "test_helpers.py", "test_utils.py", "test_fixtures.py"}


def _is_test_file(filename: str) -> bool:
    """Return True only for files that should contain test functions."""
    basename = filename.split("/")[-1]
    if basename in _DATA_MODULE_NAMES:
        return False
    return basename.startswith("test_") or basename.endswith("_test.py")


def _check_syntax_only(filename: str, code: str) -> ValidationResult:
    """Syntax-only check for data/helper modules that are not test suites."""
    try:
        ast.parse(code)
        return ValidationResult(filename=filename, passed=True, errors=[], warnings=[]).model_dump()
    except SyntaxError as e:
        return ValidationResult(
            filename=filename,
            passed=False,
            errors=[f"SyntaxError at line {e.lineno}: {e.msg}"],
        ).model_dump()


def _is_data_module(filename: str) -> bool:
    return filename.split("/")[-1] in _DATA_MODULE_NAMES


def run_validation_agent(state: TestFlowState) -> dict:
    generated = state.get("generated_tests", {})
    results = []
    for fname, code in generated.items():
        if _is_test_file(fname):
            results.append(_check_code(fname, code))
        elif _is_data_module(fname):
            # Syntax-check only — data modules have no test functions or playwright imports
            results.append(_check_syntax_only(fname, code))
        # conftest.py, pages/, __init__.py, pytest.ini etc. are skipped entirely
    all_passed = all(r["passed"] for r in results)

    return {
        "validation_results": results,
        "current_stage": PipelineStage.EXPORT if all_passed else PipelineStage.CODE_GENERATION,
    }
