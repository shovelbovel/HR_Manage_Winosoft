"""Dedicated filtering component called before every outbound request to
the AI provider, per the cahier des charges' Module 12 data-protection
table: "Le filtrage est effectué par un composant dédié appelé avant
chaque requête sortante." A denylist, checked recursively, not an
allowlist — new sensitive fields must be added here explicitly.
"""

from __future__ import annotations

_SENSITIVE_KEYS = {
    "gross_salary",
    "gross_salary_encrypted",
    "net_salary",
    "rib",
    "rib_encrypted",
    "cnss_number",
    "cin",
    "birth_date",
    "emergency_contact_name",
    "emergency_contact_phone",
    "internal_notes",
}


class SensitiveDataError(Exception):
    """Raised when a payload about to be sent to the AI provider contains
    a field the cahier des charges forbids transmitting. This should never
    trigger given how payloads are hand-built in app.services.ai_service —
    it's a real guard against a future regression, not decorative.
    """

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Payload contains a forbidden sensitive field: {key!r}")


def assert_no_sensitive_keys(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _SENSITIVE_KEYS:
                raise SensitiveDataError(key)
            assert_no_sensitive_keys(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_no_sensitive_keys(item)
