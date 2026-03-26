"""
Test Code Generation Agent.

Converts approved test cases into runnable Python/Playwright code following
Page Object Model, pytest conventions, and senior-engineer best practices.
"""

import json
import re

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agents.state import TestFlowState, PipelineStage
from backend.config.llm import get_llm


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output (handles all variants)."""
    text = text.strip()
    m = re.match(r'^```(?:json)?\s*\n?(.*?)\n?```\s*$', text, re.DOTALL)
    return m.group(1).strip() if m else text


# ── conftest template ─────────────────────────────────────────────────────────
# Embedded here so the LLM receives an exact, authoritative template.
# The executor also has its own fallback conftest; the LLM-generated one takes
# precedence (executor checks `if not conftest.exists()` before writing).

_CONFTEST_TEMPLATE = '''\
import os
import pytest
from playwright.sync_api import sync_playwright, Page

# Browser launch args: required inside Docker/CI, harmless on desktop.
_BROWSER_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox",
    "--disable-dev-shm-usage", "--disable-gpu",
    "--no-zygote", "--disable-extensions",
]


# ── core fixtures (DO NOT modify) ─────────────────────────────────────────────

@pytest.fixture
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=_BROWSER_ARGS, timeout=30_000)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(ignore_https_errors=True)
    pg = ctx.new_page()
    pg.set_default_timeout(20_000)
    pg.set_default_navigation_timeout(30_000)
    yield pg
    ctx.close()


# ── observability ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def screenshot_on_failure(page: Page, request):
    """Capture a screenshot automatically when a test fails."""
    yield
    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        screenshots_dir = "screenshots"
        os.makedirs(screenshots_dir, exist_ok=True)
        safe_name = request.node.name.replace("/", "_").replace("::", "__")
        path = f"{screenshots_dir}/{safe_name}.png"
        try:
            page.screenshot(path=path, full_page=True)
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


# ── domain fixtures (add shared setup here) ───────────────────────────────────
# Example — uncomment and adapt:
#
# @pytest.fixture
# def logged_in_page(page: Page) -> "DashboardPage":
#     from pages.login_page import LoginPage
#     return LoginPage(page).navigate().login(
#         os.environ.get("TEST_USERNAME", "standard_user"),
#         os.environ.get("TEST_PASSWORD", "secret_sauce"),
#     )
'''

# ── pytest.ini template ───────────────────────────────────────────────────────

_PYTEST_INI_TEMPLATE = '''\
[pytest]
markers =
    smoke:      critical-path tests — run on every commit
    regression: full test suite — run nightly or on release branches
    slow:       tests taking more than 10 seconds
timeout = 60
filterwarnings =
    ignore::DeprecationWarning
    ignore::pytest.PytestUnknownMarkWarning
'''

# ── system prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""\
You are a senior Python automation engineer specialising in Playwright and pytest.
Produce code that looks like the work of an experienced professional: typed, DRY,
readable, YAGNI, idempotent, and easy to extend. Tests must work for ANY web
application — never hardcode site-specific assumptions.

════════════════════════════════════════════════════════════════
 REQUIRED OUTPUT FILES — always generate all of them
════════════════════════════════════════════════════════════════

Return a JSON object where keys are file paths and values are complete file contents:

{{
  "conftest.py":          "... (exact template below, + domain fixtures) ...",
  "pytest.ini":           "... (exact template below) ...",
  "pages/__init__.py":    "... (re-exports every Page class) ...",
  "pages/<x>_page.py":   "... (one file per distinct page) ...",
  "tests/test_data.py":   "... (all constants and test data) ...",
  "tests/test_<x>.py":   "... (one file per feature/page) ..."
}}

Output ONLY valid JSON. No markdown fences. No commentary outside the JSON.

════════════════════════════════════════════════════════════════
 CONFTEST.PY — use this exact template, add domain fixtures below
════════════════════════════════════════════════════════════════

{_CONFTEST_TEMPLATE}

════════════════════════════════════════════════════════════════
 PYTEST.INI — use this exact template
════════════════════════════════════════════════════════════════

{_PYTEST_INI_TEMPLATE}

════════════════════════════════════════════════════════════════
 BASE URL (CRITICAL)
════════════════════════════════════════════════════════════════

Every Page Object reads the URL from the environment — never hardcode:
    URL = os.environ.get("APP_URL", "<the provided base url>")

════════════════════════════════════════════════════════════════
 1. FLUENT PAGE OBJECT MODEL
════════════════════════════════════════════════════════════════

• One Page Object class per page → pages/<name>_page.py
• All locator lookups and multi-step action sequences belong in the Page class.
• Navigation methods return the NEXT Page Object (fluent / page-chain pattern):

    def login(self, username: str, password: str) -> "DashboardPage":
        \"\"\"Submit login form and return the resulting page.\"\"\"
        from pages.dashboard_page import DashboardPage
        self.page.get_by_label("Username", exact=False).fill(username)
        self.page.get_by_label("Password", exact=False).fill(password)
        self.page.get_by_role("button", name="Login", exact=False).click()
        self.page.wait_for_load_state("networkidle")
        return DashboardPage(self.page)

• State-check methods return bool:  is_error_visible() -> bool
• Data-retrieval methods return value: get_cart_count() -> int
• Add __repr__ for readable debug output:
    def __repr__(self) -> str:
        return f"{{self.__class__.__name__}}(url={{self.page.url!r}})"

════════════════════════════════════════════════════════════════
 2. CONFTEST DOMAIN FIXTURES — DRY shared setup
════════════════════════════════════════════════════════════════

If 2 or more tests share the same setup (e.g. being logged in, having items in
cart), extract it as a pytest fixture in conftest.py — do NOT copy-paste setup
into individual test functions:

    @pytest.fixture
    def logged_in_page(page: Page) -> DashboardPage:
        from pages.login_page import LoginPage
        return LoginPage(page).navigate().login(
            os.environ.get("TEST_USERNAME", "standard_user"),
            os.environ.get("TEST_PASSWORD", "secret_sauce"),  # TODO: move to env
        )

Add these domain fixtures at the bottom of conftest.py after the template section.

════════════════════════════════════════════════════════════════
 3. TEST DATA — separated from test logic
════════════════════════════════════════════════════════════════

All constants and test data live in tests/test_data.py, imported by tests:

    # tests/test_data.py
    from __future__ import annotations
    import os

    VALID_USER = {{
        "username": os.environ.get("TEST_USERNAME", "standard_user"),  # TODO: env
        "password": os.environ.get("TEST_PASSWORD", "secret_sauce"),   # TODO: env
    }}
    LOCKED_USER = {{"username": "locked_out_user", "password": "secret_sauce"}}
    EXPECTED_PRODUCT_COUNT = 6

Never embed magic strings or numbers directly in test functions.

════════════════════════════════════════════════════════════════
 4. NEGATIVE TEST COVERAGE
════════════════════════════════════════════════════════════════

For every happy-path test, generate a corresponding negative test where meaningful:
    def test_login_when_invalid_credentials_expects_error_message(...)
    def test_checkout_when_cart_empty_expects_warning(...)

Negative tests use @pytest.mark.regression (not smoke).

════════════════════════════════════════════════════════════════
 5. TYPE HINTS — on everything
════════════════════════════════════════════════════════════════

CRITICAL — `from __future__ import annotations` MUST be the very first line of
every .py file (before any other import, docstring, or blank line). Python raises
a SyntaxError if any import or statement precedes it.

    # CORRECT                          # WRONG
    from __future__ import annotations  import os
    import os                           from __future__ import annotations  ← SyntaxError

Every method, parameter, and return value must be typed:
    def navigate(self) -> "LoginPage": ...
    def get_error_message(self) -> str: ...
    def is_add_to_cart_visible(self) -> bool: ...
    def test_login_succeeds(self, page: Page) -> None: ...

════════════════════════════════════════════════════════════════
 6. AAA STRUCTURE — Arrange / Act / Assert
════════════════════════════════════════════════════════════════

In tests with more than ~5 lines, mark the three sections explicitly:
    def test_cart_total_updates_after_adding_item(...) -> None:
        # Arrange
        cart = CartPage(page).navigate()

        # Act
        cart.add_item("Sauce Labs Backpack")

        # Assert
        assert cart.get_item_count() == 1, "Expected 1 item after adding one"

════════════════════════════════════════════════════════════════
 7. PAGE OBJECT METHOD NAMING CONVENTIONS
════════════════════════════════════════════════════════════════

Prefix methods by their category so the intent is instantly clear:
    navigate()          → go to the page URL and wait for load
    click_<element>()   → click a specific element
    fill_<field>(value) → fill an input field
    get_<data>()        → return a value from the page
    is_<state>()        → return bool (element visible, error shown, etc.)
    wait_for_<state>()  → block until a condition is true

════════════════════════════════════════════════════════════════
 8. CONSTANTS — no magic literals
════════════════════════════════════════════════════════════════

Any string or number appearing more than once must be a named constant in
tests/test_data.py or as a class-level attribute:
    EXPECTED_PRODUCTS = 6          # not `== 6` inline
    MAX_ADD_ITERATIONS = 20        # guard for while-loops
    CART_BADGE_ROLE = "status"     # ARIA role used for cart badge

════════════════════════════════════════════════════════════════
 9. TEST NAMING — describes behaviour, not implementation
════════════════════════════════════════════════════════════════

Pattern: test_<action>_when_<context>_expects_<result>
    test_login_when_valid_credentials_expects_dashboard
    test_cart_badge_when_all_items_added_expects_count_equals_six
    test_checkout_when_cart_empty_expects_proceed_button_disabled

Docstring on every test:
    \"\"\"TC-007: Cart badge increments after each product is added.\"\"\"

════════════════════════════════════════════════════════════════
 10. SCREENSHOT ON FAILURE — already in conftest template above
════════════════════════════════════════════════════════════════

The screenshot_on_failure fixture is autouse — no action needed in tests.
Screenshots are saved to screenshots/<test_name>.png on failure.

════════════════════════════════════════════════════════════════
 11. PYTEST MARKS — every test must have one
════════════════════════════════════════════════════════════════

Apply based on TC priority / scope:
    @pytest.mark.smoke      → critical path, highest priority TCs
    @pytest.mark.regression → full suite, normal priority
    @pytest.mark.slow       → known slow tests (>10 s, e.g. file uploads)

Multiple marks are allowed: @pytest.mark.smoke @pytest.mark.regression

════════════════════════════════════════════════════════════════
 12. IDEMPOTENCY — tests run in any order, any number of times
════════════════════════════════════════════════════════════════

• Each test sets up its own state from scratch — no dependency on previous tests.
• Tests that create or modify data must clean up (teardown in fixture) or use
  isolated data (generated unique values, fresh page session).
• Never rely on order-dependent global state or leftover browser cookies.

════════════════════════════════════════════════════════════════
 13. ROBUST WAITS — no time.sleep()
════════════════════════════════════════════════════════════════

    page.wait_for_load_state("networkidle")       after every navigation
    expect(locator).to_be_visible()               before interacting with dynamic elements
    locator.wait_for(state="visible")             when element appears asynchronously

════════════════════════════════════════════════════════════════
 14. SEMANTIC LOCATORS — no CSS selectors, no XPath
════════════════════════════════════════════════════════════════

Use in preference order (portable across any site):
    page.get_by_role("button", name="...", exact=False)
    page.get_by_label("...", exact=False)
    page.get_by_placeholder("...", exact=False)
    page.get_by_text("...", exact=False)

════════════════════════════════════════════════════════════════
 15. STEP TRACKING — required in every test
════════════════════════════════════════════════════════════════

    print("▶ Step N: <what you are about to do>")
    <action>
    print("✓ Step N done: <what was verified>")

════════════════════════════════════════════════════════════════
 16. DESCRIPTIVE ASSERTIONS — never bare
════════════════════════════════════════════════════════════════

    assert actual == expected, f"Step N: Expected '{{expected}}', got '{{actual}}'"
    expect(locator, f"Step N: <element> should be visible").to_be_visible()

════════════════════════════════════════════════════════════════
 17. NO VACUOUS PASSES
════════════════════════════════════════════════════════════════

• Assert .all() list is non-empty before iterating.
• Assert processed count > 0 after loops.
• While-loops need a max-iteration guard + final assertion.
• No bare try/except that swallows failures.
"""


def run_test_generation_agent(state: TestFlowState) -> dict:
    llm = get_llm()

    approved = [tc for tc in state["test_cases"] if tc.get("approved", False)]
    if not approved:
        approved = state["test_cases"]

    cases_text = json.dumps(approved, ensure_ascii=False, indent=2)
    app_url = state.get("app_url", "http://localhost:3000")

    # Include validation errors if this is a retry
    validation_results = state.get("validation_results", [])
    failed_results = [r for r in validation_results if not r.get("passed", True)]
    error_context = ""
    if failed_results:
        lines = []
        for r in failed_results:
            for e in r.get("errors", []):
                lines.append(f"  - [{r['filename']}] {e}")
        error_context = (
            "\n\nCRITICAL — previous attempt had these errors that MUST be fixed:\n"
            + "\n".join(lines)
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Application base URL: {app_url}\n"
            f"Use this URL in every Page class via APP_URL env var.\n\n"
            f"Test cases to implement:\n\n{cases_text}"
            f"{error_context}"
        )),
    ]

    response = llm.invoke(messages)
    raw = _strip_fences(response.content)

    try:
        generated = json.loads(raw)
    except Exception:
        generated = {"tests/test_generated.py": raw}

    retry_count = state.get("retry_count", 0)

    return {
        "generated_tests": generated,
        "current_stage": PipelineStage.VALIDATION,
        "retry_count": retry_count + 1,
    }
