# Home Assistant integration

This is the Home Assistant side of policy-tracker: how account values
reach Home Assistant, and how to install the package and dashboard
card. The scraper that produces the values (`tracker.py`) is a
separate piece; this covers [ha_mqtt.py](../ha_mqtt.py) and the files
in this folder.

## How it works

For each configured account, `ha_mqtt.py` publishes:

- one MQTT discovery message per monetary field (e.g. fund value,
  transfer value), each a `device_class: monetary` sensor
- a "last updated" timestamp sensor
- a "status" sensor with state `ok`, `otp_required`, or `error`

All entities for an account are grouped under one Home Assistant
device. All MQTT messages are published retained, so values survive a
Home Assistant restart. Object ids follow the pattern
`policy_tracker_<account_id>_<field_id>` (and `..._status`,
`..._last_updated`), which the package below relies on to find them.

On a failed run (`otp_required` or `error`), only the status sensor is
published - the last good field values stay retained and unchanged.

## Installing the package

1. If Home Assistant isn't already set up for packages, add to
   `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Copy [policy_tracker_package.yaml](policy_tracker_package.yaml) to
   `config/packages/policy_tracker_package.yaml`.
3. Restart Home Assistant.

This adds two template sensors:

- `sensor.policy_tracker_total_value` - sum of every
  `device_class: monetary` sensor whose entity id starts with
  `policy_tracker_` (so new accounts/fields are picked up
  automatically, no edits needed here)
- `sensor.policy_tracker_problem_accounts` - count of accounts whose
  status sensor is `otp_required` or `error`

and one automation that fires when that count is above zero, posting
a persistent notification per affected account naming the command to
run (`--interactive <id>` for an OTP, or where to check logs for an
error). Swap `persistent_notification.create` in the automation for a
`notify.mobile_app_<device>` call if you want a push notification
instead.

## Adding the dashboard card

Open the target dashboard view, choose "Edit in YAML" (or the Raw
configuration editor for the whole dashboard), and paste the contents
of [dashboard_card.yaml](dashboard_card.yaml) into the view's `cards:`
list. Update the entity ids to match your real accounts - see
Settings > Devices & services > Entities and filter by
"policy_tracker" once you've run a publish. Both cards are built-in
Lovelace types, so they pick up your dashboard's active theme (dark or
otherwise) without any color overrides.

## Required environment variables

`ha_mqtt.py` connects to your existing Mosquitto broker using:

| Variable        | Required | Default |
|-----------------|----------|---------|
| `MQTT_HOST`     | yes      | -       |
| `MQTT_PORT`     | no       | `1883`  |
| `MQTT_USERNAME` | no       | -       |
| `MQTT_PASSWORD` | no       | -       |

Set these in the `.env` file loaded by the systemd service (see the
project's main README for that setup). Never put them in YAML or
commit them.

## Trying it without the scraper

```bash
export MQTT_HOST=192.168.1.50   # your broker's address
python3 ha_mqtt.py --demo
```

This publishes one fake "L&G Workplace Pension" account with a fund
value of 12345.67. Check Settings > Devices & services > MQTT in Home
Assistant for a new "L&G Workplace Pension" device with three
entities, then add the package and dashboard card above.

## Tests

```bash
python3 -m pytest tests/test_ha_mqtt.py -v
```

Covers discovery message shape (device info, device_class, topics)
and the success/otp_required/error state-publishing rules. These are
pure unit tests - they don't need a running broker.
