"""
Test execution engine.

Writes generated test files to a temp directory and runs pytest.
Returns stdout, stderr, and a parsed result summary.

run_tests()           — blocking, returns full result dict
run_tests_streaming() — same but calls on_line(line) for each stdout line in real time
"""

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable


# Matches http/https on localhost or 127.0.0.1 with optional port and trailing slash
_LOCALHOST_PATTERN = re.compile(
    r'https?://(localhost|127\.0\.0\.1)(:\d+)?/?'
)


def _patch_urls(code: str, app_url: str) -> str:
    """Replace any hardcoded localhost/127.0.0.1 URL with the real app_url."""
    base = app_url.rstrip('/')
    return _LOCALHOST_PATTERN.sub(base, code)


_FUTURE_ANNOTATIONS = re.compile(r'^from __future__ import annotations[ \t]*\n?', re.MULTILINE)


def _fix_future_import(code: str) -> str:
    """Move `from __future__ import annotations` to line 1 if the LLM placed it after other imports.

    Python raises SyntaxError if any non-docstring, non-comment statement precedes it.
    Safe to call when the line is already first — the substitution is idempotent.
    """
    if 'from __future__ import annotations' not in code:
        return code
    # Remove all occurrences then prepend once
    stripped = _FUTURE_ANNOTATIONS.sub('', code)
    return 'from __future__ import annotations\n' + stripped


def run_tests(generated_tests: dict[str, str], app_url: str = "https://www.saucedemo.com") -> dict[str, Any]:
    """
    Write generated test files to a temp dir and execute them with pytest.

    Args:
        generated_tests: dict mapping filepath (e.g. "tests/test_login.py") to code string.
        app_url: base URL of the application under test — replaces any localhost refs.

    Returns:
        {
            "status": "passed" | "failed" | "error",
            "stdout": str,
            "stderr": str,
            "test_count": int,
            "pass_count": int,
            "fail_count": int,
        }
    """
    with tempfile.TemporaryDirectory(prefix="testflow_run_") as tmpdir:
        # Write all files, patching any remaining hardcoded localhost URLs
        for rel_path, code in generated_tests.items():
            full_path = Path(tmpdir) / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(_fix_future_import(_patch_urls(code, app_url)), encoding="utf-8")

        # Write conftest.py if the generated files didn't include one.
        # Use the canonical template from the generation agent (single source of truth).
        conftest = Path(tmpdir) / "conftest.py"
        if not conftest.exists():
            from backend.agents.test_generation_agent import _CONFTEST_TEMPLATE
            conftest.write_text(_CONFTEST_TEMPLATE, encoding="utf-8")

        try:
            proc = subprocess.run(
                [
                    "pytest",
                    "--tb=short",
                    "-q",
                    "-p", "no:playwright",
                    "--timeout=60",
                    # "." runs all tests in tmpdir; with cwd=tmpdir pytest uses tmpdir
                    # as rootdir so verbose output shows relative paths (e.g.
                    # "tests/test_login.py::...") instead of absolute /tmp/... paths.
                    ".",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=tmpdir,
                env={**os.environ, "PYTHONPATH": tmpdir, "APP_URL": app_url},
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "stdout": "",
                "stderr": "Test run timed out after 300 seconds.",
                "test_count": 0,
                "pass_count": 0,
                "fail_count": 0,
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "stdout": "",
                "stderr": "pytest not found in PATH.",
                "test_count": 0,
                "pass_count": 0,
                "fail_count": 0,
            }

        stdout = proc.stdout
        stderr = proc.stderr

        test_count, pass_count, fail_count = _parse_pytest_summary(stdout)
        status = "passed" if proc.returncode == 0 else "failed"
        if proc.returncode not in (0, 1):
            status = "error"

        return {
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "test_count": test_count,
            "pass_count": pass_count,
            "fail_count": fail_count,
        }


_PYTEST_CMD = [
    "pytest",
    "--tb=long",           # full source context in tracebacks for easier debugging
    "-v",                  # verbose: one line per test so streaming is meaningful
    "-s",                  # disable output capture so print() step-tracking is visible
    "-p", "no:playwright", # use our conftest fixtures, not pytest-playwright's
    "--timeout=60",        # per-test limit so one hang doesn't block the suite
]


def run_tests_streaming(
    generated_tests: dict[str, str],
    app_url: str = "https://www.saucedemo.com",
    on_line: Callable[[str], None] | None = None,
    test_filter: str | None = None,
) -> dict[str, Any]:
    """
    Like run_tests() but calls on_line(line) for each stdout line as it arrives.
    Runs pytest via Popen so output is streamed in real time instead of buffered.
    Safe to call from a threadpool worker.

    test_filter: optional pytest node id relative to the generated files root,
                 e.g. "tests/test_cart.py" or "tests/test_cart.py::TestCart::test_add".
                 When None, the whole tmpdir is passed to pytest (run all tests).
    """
    with tempfile.TemporaryDirectory(prefix="testflow_run_") as tmpdir:
        for rel_path, code in generated_tests.items():
            full_path = Path(tmpdir) / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(_fix_future_import(_patch_urls(code, app_url)), encoding="utf-8")

        conftest = Path(tmpdir) / "conftest.py"
        if not conftest.exists():
            from backend.agents.test_generation_agent import _CONFTEST_TEMPLATE
            conftest.write_text(_CONFTEST_TEMPLATE, encoding="utf-8")

        # Build pytest target.
        # With cwd=tmpdir, pytest uses tmpdir as rootdir and emits relative paths
        # (e.g. "tests/test_login.py::Class::method") in verbose output — those
        # relative IDs are what the frontend stores and passes back as test_filter.
        #
        # Safety net: if test_filter is an absolute path from a previous run
        # (old tmpdir already deleted), strip the stale tmpdir prefix so only the
        # relative part (e.g. "tests/test_login.py::Class::method") is kept.
        # Resolve pytest target for single-test re-runs.
        # Strategy (handles class refactors and renames after regeneration):
        #   1. Extract file path and function name from the node ID.
        #   2. Quick --collect-only -k <func_name> to check if the name still exists.
        #   3a. Name found  → run that file scoped to -k <func_name> (1 test).
        #   3b. Name missing (renamed after regen) → run the whole file as fallback.
        if test_filter:
            rel_filter = test_filter
            stale_prefix = re.match(r'^/tmp/testflow_run_[^/]+/', test_filter)
            if stale_prefix:
                rel_filter = test_filter[stale_prefix.end():]

            parts = rel_filter.split("::")
            file_path = parts[0]
            func_name = parts[-1] if len(parts) >= 2 else None

            if func_name:
                # Fast collect-only pass — no test execution, just checks if name exists
                probe = subprocess.run(
                    ["pytest", "--collect-only", "-q", "-p", "no:playwright",
                     "--timeout=10", "-k", func_name, file_path],
                    capture_output=True, text=True, cwd=tmpdir,
                    env={**os.environ, "PYTHONPATH": tmpdir, "APP_URL": app_url},
                    timeout=30,
                )
                # pytest --collect-only -q -k ... outputs "N/M tests collected"
                found = bool(re.search(r'\b[1-9]\d*/\d+ tests? collected\b', probe.stdout))
                if found:
                    pytest_target = file_path
                    _single_test_args = ["-k", func_name]
                else:
                    # Function was renamed after regeneration — run the whole file
                    pytest_target = file_path
                    _single_test_args = []
            else:
                pytest_target = file_path
                _single_test_args = []
        else:
            pytest_target = "."
            _single_test_args = []

        try:
            proc = subprocess.Popen(
                [*_PYTEST_CMD, *_single_test_args, pytest_target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=tmpdir,
                env={**os.environ, "PYTHONPATH": tmpdir, "APP_URL": app_url},
            )
        except FileNotFoundError:
            return {
                "status": "error", "stdout": "", "test_count": 0,
                "pass_count": 0, "fail_count": 0,
                "stderr": "pytest not found in PATH.",
            }

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        # Read stderr in a background thread so it never blocks stdout reading
        def _drain_stderr():
            for line in proc.stderr:
                stderr_lines.append(line)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Hard-kill timer: if the process hangs without producing any output
        # (e.g. playwright browser download, deadlock in fixture setup),
        # `for line in proc.stdout` blocks forever and proc.wait() is never reached.
        # This timer kills the process after 300 s regardless of stdout state.
        timed_out = False

        def _hard_kill():
            nonlocal timed_out
            timed_out = True
            try:
                proc.kill()
            except OSError:
                pass

        kill_timer = threading.Timer(300, _hard_kill)
        kill_timer.start()
        try:
            for line in proc.stdout:
                stripped = line.rstrip()
                stdout_lines.append(stripped)
                if on_line:
                    on_line(stripped)
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            timed_out = True
        finally:
            kill_timer.cancel()

        stderr_thread.join(timeout=5)

        if timed_out:
            return {
                "status": "error",
                "stdout": "\n".join(stdout_lines),
                "stderr": "Test run timed out after 300 seconds.",
                "test_count": 0, "pass_count": 0, "fail_count": 0,
            }

        stdout = "\n".join(stdout_lines)
        stderr = "".join(stderr_lines)
        test_count, pass_count, fail_count = _parse_pytest_summary(stdout)
        status = "passed" if proc.returncode == 0 else "failed"
        if proc.returncode not in (0, 1):
            status = "error"

        return {
            "status": status, "stdout": stdout, "stderr": stderr,
            "test_count": test_count, "pass_count": pass_count, "fail_count": fail_count,
        }


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Extract test counts from pytest summary line, e.g. '3 passed, 1 failed'."""
    passed = failed = 0
    m_passed = re.search(r"(\d+) passed", output)
    m_failed = re.search(r"(\d+) failed", output)
    if m_passed:
        passed = int(m_passed.group(1))
    if m_failed:
        failed = int(m_failed.group(1))
    return passed + failed, passed, failed
