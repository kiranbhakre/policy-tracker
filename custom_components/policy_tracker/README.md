# Policy Tracker (native Home Assistant integration)

This is a second, alternative way to run policy-tracker: instead of a
standalone script on the Pi publishing over MQTT (see the
[project README](../../README.md) and [ha/](../../ha)), this folder is
a real `custom_components` integration that Home Assistant loads and
schedules itself, with its own config flow and sensor entities.

## Read this before installing: Chromium requirement

Home Assistant's `manifest.json` mechanism only pip-installs the
`playwright` Python *package* automatically. It does **not** install
the Chromium *browser binary* or its OS-level shared libraries - that
needs `playwright install --with-deps chromium` run inside Home
Assistant's own Python environment, with full OS package access.

This works on:

- Home Assistant **Core**, installed yourself in a Python venv on a
  machine you control (run the install command in that venv)
- Home Assistant **Container**, if you build a custom image layer
  that runs `playwright install --with-deps chromium`

This generally does **not** work on:

- Home Assistant **OS** (HAOS) or a stock **Supervised** install -
  these don't give custom integrations a way to install arbitrary
  system libraries or browser binaries

If you're on HAOS or Supervised, use the standalone script instead
(see the [project README](../../README.md)) - it runs on the Pi, not
inside Home Assistant, so it has no such restriction.

## Installing

1. Copy this `custom_components/policy_tracker` folder into your Home
   Assistant config's `custom_components/policy_tracker`.
2. Restart Home Assistant so it picks up the new integration and
   installs the `playwright` and `PyYAML` Python packages from
   `manifest.json`.
3. Separately run `playwright install --with-deps chromium` inside
   Home Assistant's own Python environment (see the caveat above -
   this step is why this integration doesn't work everywhere).
4. Settings > Devices & services > Add integration > search "Policy
   Tracker".
5. Provide:
   - **Path to accounts YAML file** - the exact same format as the
     standalone script's `config.yaml` (see
     [config.example.yaml](../../config.example.yaml)): one entry per
     account with its login steps, OTP/logged-in selectors, and
     fields.
   - **Directory for persistent browser profiles** - where Chromium's
     per-account session cookies are stored.
   - **Hours between scrapes** - defaults to 168 (weekly).

This creates one device per account, with:

- a monetary sensor per configured field
- a diagnostic `status` sensor (`ok` / `otp_required` / `error`)
- a diagnostic `last updated` timestamp sensor

A failed run only changes the status sensor - the field sensors keep
their last good value.

## Credentials

Login step values referenced by `value_env` are read from the
environment Home Assistant itself was started with (e.g. an
`EnvironmentFile=` in Core's systemd unit, or `env_file:` in a
Container's `docker-compose.yml`) - never typed into the config flow
and never stored by this integration.

## Handling a one-time code

Home Assistant has no way to show you a visible browser to type a
one-time code into. If an account's status sensor shows
`otp_required`, fix it the same way as the standalone script: run

```bash
python3 tracker.py --interactive <account_id>
```

pointed at a `config.yaml` whose `profile_dir` matches the directory
you gave this integration, then wait for the next scheduled scrape (or
reload this integration) to pick up the saved session.

## Which option should I use?

For most setups, the standalone script + MQTT (the main project
README) is simpler and more portable - it runs independently of Home
Assistant, so a Home Assistant restart or upgrade can't affect it, and
it isn't limited to installs with full OS access. This native
integration exists for people who specifically want policy-tracker
wired in as a first-class Home Assistant integration on a Home
Assistant install they fully control.
