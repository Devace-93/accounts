"""IP hashing. accounts never stores a raw IP address.

``ip_hash(ip)`` = sha256(ip + ":" + sha256(IP_HASH_SECRET)). Unlike metrics'
daily-rotating salt this one is stable: a session row keeps the same hash for
its whole life so "sessions from the same network" can be eyeballed on the
profile page. It is still useless without the secret.
"""
from __future__ import annotations

import hashlib

from .config import config


def ip_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = hashlib.sha256(config.ip_hash_secret.encode()).hexdigest()
    return hashlib.sha256(f"{ip}:{salt}".encode()).hexdigest()
