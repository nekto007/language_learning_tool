# app/admin/secret_store.py

"""Encrypt/decrypt helpers for storing third-party credentials at rest.

Used for long-lived secrets persisted in `SiteSettings` (e.g. the Google
Search Console OAuth refresh token). Plain-DB read access (dumps, backups,
read replicas, support tooling) should not expose the raw token.

Key derivation: a 32-byte Fernet key is derived from
`SECRET_STORE_KEY` (env), falling back to Flask's `SECRET_KEY` so that a
fresh deployment that already has a configured `SECRET_KEY` works without
extra configuration. Set a dedicated `SECRET_STORE_KEY` in production if
you ever rotate the Flask cookie key.

Stored ciphertext is prefixed with `enc:v1:` so that legacy plaintext rows
(written before encryption was introduced) can be detected and returned
as-is by `decrypt_secret`. New writes always go through `encrypt_secret`.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

logger = logging.getLogger(__name__)

_PREFIX = 'enc:v1:'


def _derive_key() -> bytes:
    raw = os.environ.get('SECRET_STORE_KEY') or ''
    if not raw:
        try:
            raw = current_app.config.get('SECRET_KEY') or ''
        except RuntimeError:
            raw = ''
    if not raw:
        raise RuntimeError(
            'secret_store requires SECRET_STORE_KEY or Flask SECRET_KEY to be set'
        )
    digest = hashlib.sha256(raw.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* and return a string prefixed with `enc:v1:`.

    Empty input is returned as-is so callers can clear a setting by writing ''.
    """
    if not plaintext:
        return ''
    token = Fernet(_derive_key()).encrypt(plaintext.encode('utf-8'))
    return _PREFIX + token.decode('ascii')


def decrypt_secret(value: str | None) -> str:
    """Decrypt a value previously written via `encrypt_secret`.

    Backward-compatible: a value without the `enc:v1:` prefix is treated as
    legacy plaintext and returned unchanged. Returns '' for None/empty input.
    Returns '' if decryption fails (corrupted ciphertext or wrong key) — the
    failure is logged but never raised, so the admin UI continues to function.
    """
    if not value:
        return ''
    if not value.startswith(_PREFIX):
        return value
    ciphertext = value[len(_PREFIX):].encode('ascii')
    try:
        return Fernet(_derive_key()).decrypt(ciphertext).decode('utf-8')
    except (InvalidToken, ValueError):
        logger.exception('secret_store: failed to decrypt stored value')
        return ''
