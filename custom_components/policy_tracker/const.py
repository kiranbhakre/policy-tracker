"""Constants for the Policy Tracker integration.

One config entry = one account. The account-shaped keys (name,
provider, type, login_url, logged_in_selector, otp_selector,
values_url, login_steps, fields) are the same field names
scraper.parse_account() already expects and validates - they're not
redefined here as constants since parse_account is their one source
of truth.
"""

DOMAIN = "policy_tracker"

CONF_PROFILE_DIR = "profile_dir"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"
CONF_CREDENTIALS = "credentials"  # {credential_name: value}, for this entry's one account

DEFAULT_PROFILE_DIR = "policy_tracker_profiles"
DEFAULT_SCAN_INTERVAL_HOURS = 168  # weekly, matching the standalone script's timer

ACTIONS = ("fill", "click", "wait")
FILL_VALUE_SOURCES = ("credential", "literal", "env")
FIELD_EXTRACTION_METHODS = ("label", "selector")
ACCOUNT_TYPES = ("pension", "policy")

STATUS_OK = "ok"
STATUS_OTP_REQUIRED = "otp_required"
STATUS_ERROR = "error"
