"""Built-in provider profiles: known login flows and field definitions.

These exist so a well-known provider's account can be set up with
just a name and credentials, instead of walking through the generic
multi-step wizard in config_flow.py (which remains available, and is
still the only option for a provider without a profile here).

Each profile is a plain dict in exactly the shape scraper.parse_account()
already expects (the same shape the generic wizard assembles), minus
"name" and "id" - the config flow fills those in. Credentials are
always named "username" and "password" here; the config flow's
known-provider screen asks for exactly those two.
"""

from __future__ import annotations

# Legal & General's "My Account" portal (myaccount.landg.com) is a
# ForgeRock-based multi-step login journey: one page for the
# email/User ID, then a separate page for the password, then a
# "Continue" submit on each. Confirmed by direct inspection on
# 2026-11-13, including a real login through to the password page:
#   - the identifier field's id is "lg-input-0"
#   - the submit button has no stable id, just type="submit"
#   - the password field has its own stable selector,
#     [data-testid="password"] - a different element from the
#     identifier field, not a reused id as originally guessed
#   - [data-testid="logout-nav-link"] exists only once logged in
#   - the workplace pension's balance is the first GBP amount after
#     the text "Workplace Pension" on the account dashboard
#
# NOT confirmed (never completed a login past the password page):
#   - whether/when a one-time-code page appears, and its selector -
#     left as None, so a code prompt will currently surface as
#     status "error" rather than "otp_required" until confirmed.
LEGAL_AND_GENERAL_WORKPLACE_PENSION: dict = {
    "provider": "Legal & General",
    "type": "pension",
    "login_url": "https://myaccount.landg.com/",
    "logged_in_selector": '[data-testid="logout-nav-link"]',
    "otp_selector": None,
    "login_steps": [
        {"action": "fill", "selector": "#lg-input-0", "value_credential": "username"},
        {"action": "click", "selector": "button[type=submit]"},
        {"action": "wait", "wait_ms": 2000},
        {"action": "fill", "selector": '[data-testid="password"]', "value_credential": "password"},
        {"action": "click", "selector": "button[type=submit]"},
    ],
    "fields": [
        {"id": "fund_value", "label": "Workplace Pension"},
    ],
}

KNOWN_PROVIDERS: dict[str, dict] = {
    "lg_workplace_pension": LEGAL_AND_GENERAL_WORKPLACE_PENSION,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "lg_workplace_pension": "Legal & General - Workplace Pension",
}

CUSTOM_PROVIDER_KEY = "custom"
