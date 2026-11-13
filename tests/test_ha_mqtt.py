"""Unit tests for ha_mqtt discovery and state message construction."""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ha_mqtt import (
    AccountConfig,
    AccountResult,
    FieldSpec,
    discovery_messages,
    discovery_topic,
    state_messages,
    state_topic,
)


@pytest.fixture
def account() -> AccountConfig:
    return AccountConfig(
        id="lg_pension",
        name="L&G Workplace Pension",
        provider="Legal & General",
        type="pension",
        fields=(
            FieldSpec("fund_value", "Fund value"),
            FieldSpec("transfer_value", "Transfer value"),
        ),
    )


def test_discovery_messages_cover_status_last_updated_and_each_field(account):
    messages = discovery_messages(account)
    object_ids = {payload["object_id"] for _, payload in messages}
    assert object_ids == {
        "policy_tracker_lg_pension_status",
        "policy_tracker_lg_pension_last_updated",
        "policy_tracker_lg_pension_fund_value",
        "policy_tracker_lg_pension_transfer_value",
    }


def test_field_discovery_payload_has_monetary_device_class(account):
    messages = discovery_messages(account)
    field_payload = next(
        p for _, p in messages if p["object_id"] == "policy_tracker_lg_pension_fund_value"
    )
    assert field_payload["device_class"] == "monetary"
    assert field_payload["state_class"] == "total"
    assert field_payload["unit_of_measurement"] == "GBP"
    assert field_payload["device"]["identifiers"] == ["policy_tracker_lg_pension"]
    assert field_payload["device"]["manufacturer"] == "Legal & General"


def test_status_discovery_lists_valid_options(account):
    messages = discovery_messages(account)
    status_payload = next(
        p for _, p in messages if p["object_id"] == "policy_tracker_lg_pension_status"
    )
    assert status_payload["options"] == ["ok", "otp_required", "error"]
    assert status_payload["device_class"] == "enum"


def test_discovery_and_state_topics_match_object_id():
    object_id = "policy_tracker_lg_pension_fund_value"
    assert discovery_topic(object_id) == (
        "homeassistant/sensor/policy_tracker/policy_tracker_lg_pension_fund_value/config"
    )
    assert state_topic(object_id) == "policy_tracker/policy_tracker_lg_pension_fund_value/state"


def test_successful_result_publishes_all_fields_status_and_last_updated(account):
    result = AccountResult(
        status="ok",
        values={"fund_value": Decimal("12345.67"), "transfer_value": Decimal("11000")},
        last_updated=datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc),
    )
    messages = dict(state_messages(account, result))
    assert messages[state_topic("policy_tracker_lg_pension_status")] == "ok"
    assert messages[state_topic("policy_tracker_lg_pension_fund_value")] == "12345.67"
    assert messages[state_topic("policy_tracker_lg_pension_transfer_value")] == "11000.00"
    assert messages[state_topic("policy_tracker_lg_pension_last_updated")] == "2026-11-13T09:30:00+00:00"


def test_otp_required_result_only_publishes_status(account):
    result = AccountResult(status="otp_required")
    messages = state_messages(account, result)
    assert messages == [(state_topic("policy_tracker_lg_pension_status"), "otp_required")]


def test_error_result_keeps_last_good_value_by_not_publishing_fields(account):
    result = AccountResult(status="error", error_message="login failed")
    messages = state_messages(account, result)
    assert len(messages) == 1
    assert messages[0][1] == "error"


def test_partial_field_values_only_publish_available_fields(account):
    result = AccountResult(
        status="ok",
        values={"fund_value": Decimal("500")},
        last_updated=datetime.now(timezone.utc),
    )
    messages = dict(state_messages(account, result))
    assert state_topic("policy_tracker_lg_pension_fund_value") in messages
    assert state_topic("policy_tracker_lg_pension_transfer_value") not in messages


def test_invalid_status_raises_value_error():
    with pytest.raises(ValueError):
        AccountResult(status="bogus")
