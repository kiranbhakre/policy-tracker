"""Unit tests for the Policy Tracker config flow's pure helper logic.

config_flow.py imports from `homeassistant` at module level (it needs
real selector/config_entries classes), so - unlike tests/test_tracker.py
and tests/test_policy_tracker_integration.py - this file needs a
Python environment with `homeassistant` installed to even import it.
It will not run under the project's own .venv (which only has
playwright/PyYAML/pytest, matching the standalone script's
dependencies). Run it with whatever interpreter has `homeassistant`
installed, e.g. the one used to confirm custom_components/policy_tracker
imports cleanly in development.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "homeassistant", reason="config_flow.py needs the homeassistant package to import - see module docstring"
)

# config_flow.py uses relative imports (`from .const import ...`), so it
# must be imported through its real package path, not as a bare
# top-level module.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from custom_components.policy_tracker.config_flow import (  # noqa: E402
    _field_from_input,
    _login_step_from_input,
)


# --- _login_step_from_input -------------------------------------------


def _login_step_input(**overrides) -> dict:
    base = {
        "action": "fill",
        "selector": "#user",
        "value_source": "credential",
        "credential_name": "username",
        "literal_value": "",
        "env_var_name": "",
        "wait_ms": 1000,
        "add_another": True,
    }
    base.update(overrides)
    return base


def test_login_step_fill_with_credential_source():
    step = _login_step_from_input(_login_step_input())
    assert step == {"action": "fill", "selector": "#user", "value_credential": "username"}


def test_login_step_fill_with_env_source():
    step = _login_step_from_input(
        _login_step_input(value_source="env", credential_name="", env_var_name="ACC_USER")
    )
    assert step == {"action": "fill", "selector": "#user", "value_env": "ACC_USER"}


def test_login_step_fill_with_literal_source():
    step = _login_step_from_input(
        _login_step_input(value_source="literal", credential_name="", literal_value="someuser")
    )
    assert step == {"action": "fill", "selector": "#user", "value": "someuser"}


def test_login_step_fill_without_selector_is_invalid():
    step = _login_step_from_input(_login_step_input(selector=""))
    assert step is None


def test_login_step_fill_without_value_source_is_invalid():
    step = _login_step_from_input(_login_step_input(value_source="", credential_name=""))
    assert step is None


def test_login_step_fill_credential_source_without_name_is_invalid():
    step = _login_step_from_input(_login_step_input(credential_name=""))
    assert step is None


def test_login_step_click():
    step = _login_step_from_input(_login_step_input(action="click", selector="#submit"))
    assert step == {"action": "click", "selector": "#submit"}


def test_login_step_click_without_selector_is_invalid():
    step = _login_step_from_input(_login_step_input(action="click", selector=""))
    assert step is None


def test_login_step_wait_with_selector_ignores_wait_ms():
    step = _login_step_from_input(_login_step_input(action="wait", selector="#done", wait_ms=5000))
    assert step == {"action": "wait", "selector": "#done"}


def test_login_step_wait_without_selector_uses_wait_ms():
    step = _login_step_from_input(_login_step_input(action="wait", selector="", wait_ms=2000))
    assert step == {"action": "wait", "wait_ms": 2000}


# --- _field_from_input --------------------------------------------------


def test_field_by_label():
    field = _field_from_input({"field_id": "fund_value", "extraction_method": "label", "label": "Fund value", "selector": ""})
    assert field == {"id": "fund_value", "label": "Fund value"}


def test_field_by_selector():
    field = _field_from_input(
        {"field_id": "fund_value", "extraction_method": "selector", "label": "", "selector": ".amount"}
    )
    assert field == {"id": "fund_value", "selector": ".amount"}


def test_field_by_label_without_label_text_is_invalid():
    field = _field_from_input({"field_id": "fund_value", "extraction_method": "label", "label": "", "selector": ""})
    assert field is None


def test_field_by_selector_without_selector_is_invalid():
    field = _field_from_input(
        {"field_id": "fund_value", "extraction_method": "selector", "label": "", "selector": ""}
    )
    assert field is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
