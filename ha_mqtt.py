"""Home Assistant MQTT integration for the policy-tracker project.

Publishes MQTT discovery messages and state updates so Home Assistant
represents each pension/policy account as a device with one monetary
sensor per field, a "last updated" timestamp sensor, and a "status"
sensor (ok / otp_required / error). Messages are retained so values
survive Home Assistant restarts, and a failed run only updates the
status sensor, leaving the last good values in place.

The scraper (tracker.py) is expected to build an AccountConfig once
per configured account and an AccountResult once per run, then call
publish_account() for each. See ha/README.md for the companion Home
Assistant package and dashboard card, and run this file with --demo
to publish one fake account without a scraper.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import paho.mqtt.client as mqtt

LOG = logging.getLogger("policy_tracker.ha_mqtt")

DISCOVERY_PREFIX = "homeassistant"
STATE_PREFIX = "policy_tracker"
ENTITY_PREFIX = "policy_tracker"

VALID_STATUSES = ("ok", "otp_required", "error")


@dataclass(frozen=True)
class FieldSpec:
    """One monetary field read from a provider portal (e.g. fund value)."""

    id: str
    label: str


@dataclass(frozen=True)
class AccountConfig:
    """Static, config-driven description of one pension/policy account."""

    id: str
    name: str
    provider: str
    type: str  # "pension" or "policy"
    fields: tuple[FieldSpec, ...]


@dataclass(frozen=True)
class AccountResult:
    """Outcome of one scrape run for an account."""

    status: str  # one of VALID_STATUSES
    values: dict[str, Decimal] = field(default_factory=dict)
    last_updated: Optional[datetime] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")


def _entity_slug(account: AccountConfig, suffix: str) -> str:
    """Build the Home Assistant object_id for one of an account's entities."""
    return f"{ENTITY_PREFIX}_{account.id}_{suffix}"


def _device_info(account: AccountConfig) -> dict:
    """Shared Home Assistant 'device' block grouping an account's entities."""
    return {
        "identifiers": [f"{ENTITY_PREFIX}_{account.id}"],
        "name": account.name,
        "manufacturer": account.provider,
        "model": account.type,
    }


def discovery_topic(object_id: str) -> str:
    """MQTT discovery config topic for a given object_id."""
    return f"{DISCOVERY_PREFIX}/sensor/{ENTITY_PREFIX}/{object_id}/config"


def state_topic(object_id: str) -> str:
    """MQTT state topic for a given object_id."""
    return f"{STATE_PREFIX}/{object_id}/state"


def _field_discovery(account: AccountConfig, spec: FieldSpec) -> tuple[str, dict]:
    object_id = _entity_slug(account, spec.id)
    payload = {
        "name": spec.label,
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": state_topic(object_id),
        "unit_of_measurement": "GBP",
        "device_class": "monetary",
        "state_class": "total",
        "device": _device_info(account),
    }
    return discovery_topic(object_id), payload


def _status_discovery(account: AccountConfig) -> tuple[str, dict]:
    object_id = _entity_slug(account, "status")
    payload = {
        "name": f"{account.name} status",
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": state_topic(object_id),
        "device_class": "enum",
        "options": list(VALID_STATUSES),
        "icon": "mdi:cloud-alert",
        "entity_category": "diagnostic",
        "device": _device_info(account),
    }
    return discovery_topic(object_id), payload


def _last_updated_discovery(account: AccountConfig) -> tuple[str, dict]:
    object_id = _entity_slug(account, "last_updated")
    payload = {
        "name": f"{account.name} last updated",
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": state_topic(object_id),
        "device_class": "timestamp",
        "entity_category": "diagnostic",
        "device": _device_info(account),
    }
    return discovery_topic(object_id), payload


def discovery_messages(account: AccountConfig) -> list[tuple[str, dict]]:
    """All MQTT discovery (topic, payload) pairs for one account."""
    messages = [_status_discovery(account), _last_updated_discovery(account)]
    messages.extend(_field_discovery(account, spec) for spec in account.fields)
    return messages


def state_messages(account: AccountConfig, result: AccountResult) -> list[tuple[str, str]]:
    """State (topic, value) pairs to publish for one scrape result.

    On success, every field present in the result, the status, and the
    last-updated timestamp are published. On otp_required/error, only
    the status is published, so previously retained field values stay
    in Home Assistant unchanged instead of being overwritten.
    """
    messages = [(state_topic(_entity_slug(account, "status")), result.status)]
    if result.status != "ok":
        return messages

    for spec in account.fields:
        if spec.id not in result.values:
            continue
        amount = result.values[spec.id]
        object_id = _entity_slug(account, spec.id)
        messages.append((state_topic(object_id), f"{amount:.2f}"))

    last_updated = result.last_updated or datetime.now(timezone.utc)
    messages.append((state_topic(_entity_slug(account, "last_updated")), last_updated.isoformat()))
    return messages


def publish_account(client: mqtt.Client, account: AccountConfig, result: AccountResult) -> None:
    """Publish discovery config (idempotent) then state for one account."""
    for topic, payload in discovery_messages(account):
        client.publish(topic, json.dumps(payload), retain=True, qos=1)
    for topic, value in state_messages(account, result):
        client.publish(topic, value, retain=True, qos=1)
    LOG.info("published account=%s status=%s", account.id, result.status)


def connect_client() -> mqtt.Client:
    """Build and connect an MQTT client from environment variables.

    Reads MQTT_HOST (required), MQTT_PORT (default 1883), and optional
    MQTT_USERNAME/MQTT_PASSWORD. Credentials are never read from files
    other than the environment, per the project's credential policy.
    """
    host = os.environ.get("MQTT_HOST")
    if not host:
        raise RuntimeError("MQTT_HOST environment variable is not set")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if username:
        client.username_pw_set(username, password)
    client.connect(host, port)
    return client


def _demo_account() -> AccountConfig:
    return AccountConfig(
        id="lg_pension",
        name="L&G Workplace Pension",
        provider="Legal & General",
        type="pension",
        fields=(FieldSpec("fund_value", "Fund value"),),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="publish one fake account and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.demo:
        parser.print_help()
        return 1

    account = _demo_account()
    result = AccountResult(
        status="ok",
        values={"fund_value": Decimal("12345.67")},
        last_updated=datetime.now(timezone.utc),
    )
    client = connect_client()
    client.loop_start()
    publish_account(client, account, result)
    client.loop_stop()
    client.disconnect()
    LOG.info("demo publish complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
