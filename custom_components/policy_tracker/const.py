"""Constants for the Policy Tracker integration."""

DOMAIN = "policy_tracker"

CONF_ACCOUNTS_FILE = "accounts_file"
CONF_PROFILE_DIR = "profile_dir"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

DEFAULT_PROFILE_DIR = "policy_tracker_profiles"
DEFAULT_SCAN_INTERVAL_HOURS = 168  # weekly, matching the standalone script's timer

STATUS_OK = "ok"
STATUS_OTP_REQUIRED = "otp_required"
STATUS_ERROR = "error"
