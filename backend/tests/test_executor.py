"""
Tests for the pytest execution engine.
Uses real subprocess calls with trivial test code (no Playwright needed).
"""

import pytest
from backend.runner.executor import run_tests, _parse_pytest_summary


class TestParsePytestSummary:
    def test_parses_all_passed(self):
        total, passed, failed = _parse_pytest_summary("3 passed in 0.5s")
        assert total == 3
        assert passed == 3
        assert failed == 0

    def test_parses_mixed_results(self):
        total, passed, failed = _parse_pytest_summary("2 passed, 1 failed in 1.2s")
        assert total == 3
        assert passed == 2
        assert failed == 1

    def test_parses_only_failures(self):
        total, passed, failed = _parse_pytest_summary("3 failed in 0.8s")
        assert total == 3
        assert passed == 0
        assert failed == 3

    def test_empty_output(self):
        total, passed, failed = _parse_pytest_summary("")
        assert total == 0
        assert passed == 0
        assert failed == 0


class TestRunTests:
    def test_passing_test(self):
        tests = {
            "tests/test_simple.py": '''\
def test_one_plus_one():
    assert 1 + 1 == 2

def test_string():
    assert "hello".upper() == "HELLO"
'''
        }
        result = run_tests(tests)
        assert result["status"] == "passed"
        assert result["pass_count"] == 2
        assert result["fail_count"] == 0
        assert result["test_count"] == 2

    def test_failing_test(self):
        tests = {
            "tests/test_fail.py": '''\
def test_always_fails():
    assert False, "intentional failure"
'''
        }
        result = run_tests(tests)
        assert result["status"] == "failed"
        assert result["fail_count"] == 1

    def test_mixed_pass_fail(self):
        tests = {
            "tests/test_mixed.py": '''\
def test_passes():
    assert True

def test_fails():
    assert False
'''
        }
        result = run_tests(tests)
        assert result["status"] == "failed"
        assert result["pass_count"] == 1
        assert result["fail_count"] == 1

    def test_syntax_error_in_test_returns_error_status(self):
        tests = {
            "tests/test_syntax.py": "def test_broken(\n    pass"
        }
        result = run_tests(tests)
        # pytest exits with code 2 (collection error) → status "error"
        assert result["status"] == "error"

    def test_multiple_files(self):
        tests = {
            "tests/test_a.py": "def test_a(): assert True\n",
            "tests/test_b.py": "def test_b(): assert True\n",
        }
        result = run_tests(tests)
        assert result["status"] == "passed"
        assert result["pass_count"] == 2

    def test_returns_stdout(self):
        tests = {
            "tests/test_output.py": '''\
def test_with_print():
    print("hello from test")
    assert True
'''
        }
        result = run_tests(tests)
        assert result["status"] == "passed"
        assert isinstance(result["stdout"], str)
