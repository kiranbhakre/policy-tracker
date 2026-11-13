# policy-tracker

Pulls the current value of a Legal & General workplace pension and
other insurance/investment policies into Home Assistant, by logging
into each provider's customer portal with Playwright (no provider
here offers a public API) and publishing the values over MQTT
discovery.

**Check each provider's terms of use before relying on this for an
account.** Automated logins may conflict with some providers' terms.

There are two ways to run this - pick one:

1. **Standalone script + MQTT** (below): `tracker.py` runs on the Pi
   under a systemd timer and publishes over MQTT discovery. Works
   anywhere, including Home Assistant OS.
2. **Native Home Assistant integration**:
   [custom_components/policy_tracker](custom_components/policy_tracker)
   - a real integration with its own config flow and sensors, loaded
   directly by Home Assistant. Requires an HA install where you can
   install the Chromium browser binary yourself (not HAOS/Supervised)
   - see [its README](custom_components/policy_tracker/README.md) for
   why and how.

## How it fits together

- [tracker.py](tracker.py) - reads `config.yaml`, logs into each
  account's portal, reads the configured fields, and publishes the
  result.
- [ha_mqtt.py](ha_mqtt.py) - builds the MQTT discovery/state messages
  Home Assistant needs. See [ha/README.md](ha/README.md) for the
  Home Assistant package and dashboard card.
- `config.yaml` (from [config.example.yaml](config.example.yaml)) -
  every account, its login steps, and the fields to read. No
  credentials live here.
- `.env` (from [.env.example](.env.example)) - MQTT broker and portal
  credentials, read only from the environment.
- [systemd/](systemd) - a weekly timer that runs `tracker.py` on the
  Pi.

## Setup on the Raspberry Pi

```bash
cd ~/policy-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install playwright paho-mqtt PyYAML
playwright install --with-deps chromium
```

Then:

```bash
cp config.example.yaml config.yaml
cp .env.example .env
chmod 600 .env
```

Edit `.env` with your MQTT broker address and each account's
credentials, and leave `config.yaml` as a starting point - its
selectors are placeholders (see "Adding a new provider" below).

## First run

1. Log in once per account, visibly, so you can handle a one-time
   code if the provider asks for one and discover the real page
   structure:

   ```bash
   set -a; source .env; set +a
   python3 tracker.py --interactive lg_pension
   ```

   If a one-time code is requested, enter it in the browser window
   that opens, then press Enter in the terminal. The login session is
   saved in `profiles/lg_pension/` and reused by later runs.

2. Once logged in, find the real labels or selectors for each value
   you want to track:

   ```bash
   python3 tracker.py --discover lg_pension
   ```

   This prints every line on the page containing a GBP amount, with
   the line before it, e.g.:

   ```text
   'Total fund value' -> '£48,210.55'
   ```

   Edit `config.yaml`'s `fields:` for that account to use `label:
   "Total fund value"` (or a CSS `selector:` if you'd rather target a
   specific element).

   It also lists every element on the page with a `data-testid`
   attribute, if the site uses them - these tend to survive redesigns
   far better than auto-generated CSS classes do, and whichever of
   them look like a logout/sign-out control are called out
   separately as `logged_in_selector` candidates:

   ```text
   Elements with a data-testid attribute (often a more stable selector than a CSS class):
     [data-testid="logout-nav-link"]  <button>  'Log out'
     [data-testid="product__name"]  <h3>  'Workplace Pension'

   Possible logged_in_selector candidates (logout/sign-out related):
     [data-testid="logout-nav-link"]  <button>  'Log out'
   ```

3. Run a normal headless pass:

   ```bash
   python3 tracker.py
   ```

   Check Home Assistant (Settings > Devices & services > MQTT) for
   the account's device and sensors, then follow
   [ha/README.md](ha/README.md) to add the package and dashboard
   card.

4. Install the timer so this repeats weekly without you:

   ```bash
   sudo cp systemd/policy-tracker.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now policy-tracker.timer
   ```

   Edit the paths and `User=` in
   [systemd/policy-tracker.service](systemd/policy-tracker.service)
   first if your install isn't at `/home/pi/policy-tracker`.

## Adding a new provider

1. Add an account entry to `config.yaml` with placeholder selectors
   (copy the shape from `config.example.yaml`).
2. Add its username/password env vars to `.env`, matching the
   `value_env` names you used in its `login_steps`.
3. Run `--interactive <id>` to log in, handle any one-time code, and
   confirm the browser actually reaches a logged-in page - adjust
   `logged_in_selector` and `otp_selector` if needed.
4. Run `--discover <id>` to find the real field labels, and fill in
   `fields:`.
5. Run `python3 tracker.py` and confirm the new device and sensors
   appear in Home Assistant.

## Troubleshooting

- **Account stuck on `otp_required`**: run
  `python3 tracker.py --interactive <id>` once; headless runs never
  attempt to answer a one-time code by design.
- **Account shows `error`**: check
  `journalctl -u policy-tracker.service -n 50` for the error message
  logged by `tracker.py`. A provider page redesign is the most common
  cause - re-run `--discover` and update `config.yaml`.
- **A field is missing/wrong after a provider redesign**: labels
  survive redesigns better than CSS selectors; re-run `--discover` and
  switch that field to `label:` if it's currently using `selector:`.
- **Nothing appears in Home Assistant at all**: confirm `MQTT_HOST` in
  `.env` is correct and reachable from the Pi, and that Home
  Assistant's MQTT integration is using the same broker as
  Zigbee2MQTT.
- **One account fails and you want to re-run just that one**: use
  `--interactive <id>` (it scrapes and publishes immediately after
  logging in) rather than re-running the whole config.

## Tests

```bash
python3 -m pytest tests/ -v
```

Covers amount parsing, label-based extraction, and config validation
in `tracker.py`, MQTT discovery/state message construction in
`ha_mqtt.py`, and the same parsing/config logic plus the
last-good-value merge rule in the native integration's
`custom_components/policy_tracker/scraper.py`. These are pure unit
tests - no browser or broker needed, and no `homeassistant` package
dependency either (the integration's HA-framework-specific files -
`coordinator.py`, `config_flow.py`, `__init__.py`, `sensor.py` - do
need `homeassistant` installed to import; see
[its README](custom_components/policy_tracker/README.md)).
