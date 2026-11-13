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

This repo is public, so HACS (now built into Home Assistant as "the
Marketplace", as of HA 2026.11) can fetch it directly. Pick one:

**Option A - HACS/Marketplace.**

[![Add repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiranbhakre&repository=policy-tracker&category=integration)

or, in HACS/Marketplace, the three-dot menu > Custom repositories > add
`https://github.com/kiranbhakre/policy-tracker` as category
"Integration". Then find "Policy Tracker" and install it - it copies
`custom_components/policy_tracker` into your config and handles
updates afterwards. (Had this repo still been private, none of this
would work at all - per HACS's own FAQ, "Private GitHub repositories
can not be used with HACS at all," no token gets around that. See
[hacs.xyz/faq/private_repositories](https://hacs.xyz/faq/private_repositories/).)

**Option B - copy by hand.** Copy this `custom_components/policy_tracker`
folder into your Home Assistant config's `custom_components/policy_tracker`.

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

No file involved - **one config entry is one account**, built
entirely through the setup wizard. Add the integration again for
each additional pension/policy.

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=policy_tracker)

or by hand: Settings > Devices & services > Add integration > search
"Policy Tracker". First screen: pick a provider.

**Known provider (quick).** A provider in [providers.py](providers.py)
has its login flow, selectors, and fields already written into the
code - the only screen left asks for a name, your email/User ID, and
password. Currently built in:

- **Legal & General - Workplace Pension** - login URL, the identifier
  field, and the logged-in marker were confirmed by directly
  inspecting `myaccount.landg.com`. The password field's selector
  **is an educated guess, not confirmed** - L&G's login is a
  multi-step journey and the password page was never actually seen
  (that needs real credentials, which this project never enters on
  your behalf). If this account's status sensor ends up `error`
  rather than `ok`, that selector in `providers.py` is the first
  thing to fix - it's a plain Python dict, easier to correct than
  re-discovering through the UI.

**Custom / other provider.** Falls through to the full generic
wizard - up to four more screens:

1. **Account basics** - name, provider, type, login page URL,
   optional separate values page URL, a CSS selector confirming
   login succeeded, an optional CSS selector for a one-time-code
   prompt, the browser profile directory, and hours between scrapes
   (default 168, weekly).
2. **Login steps** - one at a time: `fill` (needs a selector and a
   value source - credential/literal/env), `click` (needs a
   selector), or `wait` (for a selector, or a fixed delay if left
   blank). Check "Add another login step" to keep going; uncheck it
   on the last one.
3. **Fields** - one at a time: an ID, then either a label (the first
   GBP amount found after that text) or a CSS selector. Same
   "add another" pattern.
4. **Credentials** - only appears if any login step's value source
   was "credential" - exactly those fields, nothing else, masked for
   anything named like a password.

Each screen validates what it collected before letting you continue -
e.g. a `fill` step with no selector, or a field with neither a label
nor a selector, shows an error in place rather than failing silently
later.

Once an account's selectors are confirmed working end to end, it's
worth adding it to `providers.py` as a known provider - future
accounts with the same provider (yours or anyone else using this
integration) skip the generic wizard entirely.

This creates one device for the account, with:

- a monetary sensor per configured field
- a diagnostic `status` sensor (`ok` / `otp_required` / `error`)
- a diagnostic `last updated` timestamp sensor

A failed run only changes the status sensor - the field sensors keep
their last good value.

## Credentials

For each login step, the "Login steps" screen's value source picks
how its value is supplied - you can mix sources across steps:

- **credential** - typed into the "Account credentials" screen
  (masked for anything named like "password"/"secret"/"pin") and
  stored in Home Assistant's own config entry storage
  (`.storage/core.config_entries` on the HA host) - local to that
  install. The simplest option for most people.
- **env** - read from the environment Home Assistant itself was
  started with (e.g. an `EnvironmentFile=` in Core's systemd unit, or
  `env_file:` in a Container's `docker-compose.yml`). Never typed
  into the wizard, never stored by this integration at all -
  credentials exist only in the process environment. Use this if
  you'd rather Home Assistant's own storage never hold a given
  account's password.
- **literal** - a fixed, non-secret value typed straight into the
  wizard (e.g. a security-question answer that isn't actually
  sensitive). Stored the same place as "credential".

## Handling a one-time code

Home Assistant has no way to show you a visible browser to type a
one-time code into - nothing built into this integration can fix
that. If an account's status sensor shows `otp_required`, recover it
with the project's standalone script instead, which can open a
visible browser:

1. Write a small `config.yaml` for the project's `tracker.py`
   containing just this one account - the same login URL, selectors,
   and login steps you entered in the wizard (swap `value_credential`
   for `value_env` or a literal `value`; `tracker.py` doesn't know
   about `value_credential`, that's specific to this integration's
   config flow). See [config.example.yaml](../../config.example.yaml)
   for the shape.
2. Set `profile_dir` in that file to the *same* directory you gave
   this integration, and the account's `id` to anything - it just
   needs to match between this file and the `--interactive` command
   below.
3. Run:

   ```bash
   python3 tracker.py --config config.yaml --interactive <that id>
   ```

   enter the one-time code in the browser window that opens, then
   wait for this integration's next scheduled scrape (or reload the
   integration) to pick up the saved session.

This is the one place this integration still leans on the standalone
script and its config file format - a visible browser is the only
way to answer a one-time code, and Home Assistant itself can't show
you one.

## Which option should I use?

For most setups, the standalone script + MQTT (the main project
README) is simpler and more portable - it runs independently of Home
Assistant, so a Home Assistant restart or upgrade can't affect it, and
it isn't limited to installs with full OS access. This native
integration exists for people who specifically want policy-tracker
wired in as a first-class Home Assistant integration on a Home
Assistant install they fully control.
