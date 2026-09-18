"""Application-level encryption for sensitive employee fields (salary, RIB).

Cahier des charges: "Chiffrement applicatif des données sensibles, salaires
et RIB, par clé symétrique distincte des identifiants de base. La base est
chiffrée au repos par l'hébergeur, mais un accès à la console d'administration
suffirait à lire les montants en clair : le chiffrement applicatif reste
nécessaire." Only salary and RIB get this treatment — CIN/CNSS/birth_date/
emergency contact are gated by role visibility (admin-only in templates,
excluded from AI/export payloads) but not Fernet-encrypted at rest, per the
scope the spec actually states for encryption specifically.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


class DecryptionError(Exception):
    """Raised when a stored value can't be decrypted with the current key —
    almost always means the key was rotated without re-encrypting existing
    data, or the value is corrupt."""


def encrypt(value: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    fernet = Fernet(settings.fernet_key.encode("utf-8"))
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    fernet = Fernet(settings.fernet_key.encode("utf-8"))
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("Could not decrypt value with the current FERNET_KEY") from exc
