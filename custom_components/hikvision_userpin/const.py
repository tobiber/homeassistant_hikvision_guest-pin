"""Constants for the Hikvision User & PIN Control integration."""

DOMAIN = "hikvision_userpin"

PLATFORMS = ["sensor"]

# Config keys
CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
CONF_TIMEOUT = "timeout"
CONF_PROTECTED_EMPLOYEE_NOS = "protected_employee_nos"
CONF_ALLOWED_EVENTS = "allowed_events"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_TIMEOUT = 8.0
DEFAULT_SCAN_INTERVAL = 300
DEFAULT_VERIFY_SSL = False

# Event labels
EVENT_LABELS = {
    (5, 75): "Authentifizierung erfolgreich (FaceID)",
    (5, 38): "Authentifizierung erfolgreich (Fingerprint)",
    (5, 39): "Authentifizierung fehlgeschlagen (Fingerprint)",
    (5, 8): "Karte abgelaufen",
    (5, 21): "Door unlocked",
    (5, 22): "Door locked",
}

DEFAULT_ALLOWED_EVENTS = {(5, 75), (5, 38), (5, 39), (5, 8)}

# Duration options
DURATION_OPTIONS = {
    "1d": "1 Tag",
    "7d": "7 Tage",
    "14d": "14 Tage",
    "4w": "4 Wochen",
    "3m": "3 Monate",
    "12m": "12 Monate",
    "forever": "Immer",
    "custom": "Benutzerdefiniert",
}
