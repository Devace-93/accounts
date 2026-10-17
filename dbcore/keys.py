"""Session signing keys (Ed25519) and the JWKS that relying apps fetch.

``SESSION_SIGNING_KEY`` is the base64url-encoded 32-byte private seed
(``python -m dbcore.cli genkey`` prints one). When it is empty a throwaway
key is generated at import time with a loud warning: fine for a local run,
but every restart then logs everyone out and the JWKS changes.

Rotation: set the new seed in ``SESSION_SIGNING_KEY`` and move the old
*public* key into ``SESSION_PREVIOUS_PUBLIC_KEYS`` for at least
``SESSION_TTL_MIN``; tokens signed by the old key keep verifying because the
JWKS still lists it. The ``kid`` of a key is the first 8 hex chars of the
sha256 of its raw public bytes, so it is derivable from the public key alone.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import config

log = logging.getLogger("accounts.keys")


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def kid_for(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:8]


def generate_seed() -> str:
    """A fresh base64url private seed for ``SESSION_SIGNING_KEY``."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return b64url_encode(raw)


def jwk_for(public_key: Ed25519PublicKey) -> dict:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "kid": kid_for(public_key), "x": b64url_encode(raw), "alg": "EdDSA", "use": "sig"}


@dataclass(frozen=True)
class KeyRing:
    private_key: Ed25519PrivateKey
    kid: str
    previous_public: tuple[Ed25519PublicKey, ...]

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    def jwks(self) -> dict:
        keys = [jwk_for(self.public_key)] + [jwk_for(k) for k in self.previous_public]
        return {"keys": keys}

    def public_key_by_kid(self, kid: str | None) -> Ed25519PublicKey | None:
        for key in (self.public_key, *self.previous_public):
            if kid_for(key) == kid:
                return key
        return None


def _load_private(seed_b64: str) -> Ed25519PrivateKey:
    raw = b64url_decode(seed_b64)
    if len(raw) != 32:
        raise ValueError("SESSION_SIGNING_KEY must be a base64url-encoded 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(raw)


@lru_cache(maxsize=1)
def keyring() -> KeyRing:
    if config.session_signing_key:
        private = _load_private(config.session_signing_key)
    else:
        log.warning(
            "SESSION_SIGNING_KEY is empty: using a throwaway key. Every restart logs everyone out. "
            "Generate one with `python -m dbcore.cli genkey`."
        )
        private = Ed25519PrivateKey.generate()
    previous = tuple(
        Ed25519PublicKey.from_public_bytes(b64url_decode(p)) for p in config.session_previous_public_keys
    )
    return KeyRing(private_key=private, kid=kid_for(private.public_key()), previous_public=previous)
