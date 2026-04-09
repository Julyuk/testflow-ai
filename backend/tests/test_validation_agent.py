"""
Tests for the validation agent (no LLM — pure AST logic).
This is the easiest agent to test in full without mocking.
"""

import pytest
from backend.agents.validation_agent import run_validation_agent, _check_code


class TestCheckCode:
    def test_valid_playwright_test_passes(self):
        code = '''\
import pytest
from playwright.sync_api import Page, expect

def test_login(page: Page):
    """TC-001: Login with valid credentials"""
    page.goto("https://www.saucedemo.com")
    page.get_by_placeholder("Username").fill("standard_user")
    page.get_by_placeholder("Password").fill("secret_sauce")
    page.get_by_text("Login").click()
    expect(page).to_have_url("https://www.saucedemo.com/inventory.html")
'''
        result = _check_code("tests/test_login.py", code)
        assert result["passed"] is True
        assert result["errors"] == []

    def test_syntax_error_fails(self):
        code = "def test_broken(\n    pass"
        result = _check_code("tests/test_broken.py", code)
        assert result["passed"] is False
        assert any("SyntaxError" in e for e in result["errors"])

    def test_missing_test_function_in_test_file_fails(self):
        code = '''\
import pytest
from playwright.sync_api import Page

def helper():
    pass
'''
        result = _check_code("tests/test_no_funcs.py", code)
        assert result["passed"] is False
        assert any("No test functions" in e for e in result["errors"])

    def test_page_object_file_without_test_prefix_passes_without_test_check(self):
        code = '''\
import pytest
from playwright.sync_api import Page

class LoginPage:
    def __init__(self, page: Page):
        self.page = page
'''
        result = _check_code("pages/login_page.py", code)
        assert result["passed"] is True

    def test_missing_playwright_import_produces_warning(self):
        code = '''\
import pytest

def test_something(page):
    assert True
'''
        result = _check_code("tests/test_no_pw.py", code)
        assert any("playwright" in w for w in result["warnings"])

    def test_empty_code_fails_for_test_file(self):
        result = _check_code("tests/test_empty.py", "")
        assert result["passed"] is False


class TestRunValidationAgent:
    def test_all_pass(self):
        state = {
            "generated_tests": {
                "tests/test_login.py": '''\
import pytest
from playwright.sync_api import Page

def test_login(page: Page):
    pass
''',
                "pages/login_page.py": '''\
import pytest
from playwright.sync_api import Page

class LoginPage:
    def __init__(self, page: Page):
        self.page = page
''',
            }
        }
        result = run_validation_agent(state)
        assert all(r["passed"] for r in result["validation_results"])
        assert result["current_stage"] == "export"

    def test_one_failure_routes_to_code_gen(self):
        state = {
            "generated_tests": {
                "tests/test_broken.py": "def broken(",
            }
        }
        result = run_validation_agent(state)
        assert result["current_stage"] == "code_generation"
        assert not result["validation_results"][0]["passed"]

    def test_empty_generated_tests(self):
        state = {"generated_tests": {}}
        result = run_validation_agent(state)
        assert result["validation_results"] == []
        assert result["current_stage"] == "export"
