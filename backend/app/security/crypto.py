"""Encrypt-at-rest helpers for calendar account credentials.

Uses Fernet (symmetric) rather than full database encryption: the threat
model here is physical/network access to a home device, not a hostile DB
host, so a key file with restricted permissions kept outside the git repo
is sufficient. See PLAN.md "Security & credentials".
"""

import os
import stat

from cryptography.fernet import Fernet

from ..config import settings


def _load_or_create_key() -> bytes:
    key_path = settings.encryption_key_path
    if key_path.exists():
        return key_path.read_bytes()

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except (NotImplementedError, OSError):
        # Best-effort: platforms without POSIX permission bits (e.g. a
        # Windows dev machine) just skip this; the Linux kiosk does not.
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes) -> str:
    return _fernet.decrypt(token).decode("utf-8")
