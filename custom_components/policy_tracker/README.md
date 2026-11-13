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

### Step 1: get the integration's files into Home Assistant

**HACS (now built into Home Assistant as "the Marketplace", as of HA
2026.11) cannot be used at all with this repo while it stays private.**
Per HACS's own FAQ: "Private GitHub repositories can not be used with
HACS at all" - "HACS can only get publicly available information."
This isn't a missing-token problem; there is no supported way to add a
private repo, with or without a personal access token. (An earlier
version of this README incorrectly suggested adding a token would fix
it - it won't. See [hacs.xyz/faq/private_repositories](https://hacs.xyz/faq/private_repositories/).)

So, while this repo is private, install by copying the files by hand:

Copy this `custom_components/policy_tracker` folder into your Home
Assistant config's `custom_components/policy_tracker` (scp, Samba
share, whatever you'd normally use to get files onto the Pi/HA host).

If you ever decide to make this repo public - weighing that the
scraping *code* would be visible, though credentials never are (see
"Credentials" below) - then the Marketplace/HACS "add custom
repository" button and the `hacs.json` already in this repo's root
would work normally:

[![Add repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiranbhakre&repository=policy-tracker&category=integration)

> The My Home Assistant buttons here (and in Step 3) open your own
> running Home Assistant directly, skipping manual navigation - they
> work once you've visited
> [my.home-assistant.io](https://my.home-assistant.io) from a browser
> that can also reach your instance, which most setups already are.
> They do not open anyone else's Home Assistant.

### Step 2: restart, then install Chromium

Restart Home Assistant so it picks up the new integration and installs
the `playwright` and `PyYAML` Python packages from `manifest.json`.
Then separately run `playwright install --with-deps chromium` inside
Home Assistant's own Python environment (see the caveat above - this
step is why this integration doesn't work everywhere).

### Step 3: add the integration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=policy_tracker)

or by hand: Settings > Devices & services > Add integration > search
"Policy Tracker". Provide:

- **Path to accounts YAML file** - the exact same format as the
  standalone script's `config.yaml` (see
  [config.example.yaml](../../config.example.yaml)): one entry per
  account with its login steps, OTP/logged-in selectors, and fields.
- **Directory for persistent browser profiles** - where Chromium's
  per-account session cookies are stored.
- **Hours between scrapes** - defaults to 168 (weekly).

If the accounts file can't be read or doesn't parse, the form shows an
error in place rather than failing silently.

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
