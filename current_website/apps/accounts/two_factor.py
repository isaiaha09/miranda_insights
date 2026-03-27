from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_totp_secret(length: int = 20) -> str:
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def build_totp_uri(secret: str, username: str, issuer: str = "Insights") -> str:
    issuer_quoted = quote(issuer)
    account_name = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{account_name}?secret={secret}&issuer={issuer_quoted}"


def get_totp_token(secret: str, for_time: int | None = None, interval: int = 30, digits: int = 6) -> str:
    current_time = int(for_time if for_time is not None else time.time())
    counter = current_time // interval
    normalized = secret.upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    token = binary % (10 ** digits)
    return str(token).zfill(digits)


def verify_totp(secret: str, token: str, *, window: int = 1, interval: int = 30) -> bool:
    cleaned = "".join(ch for ch in str(token or "") if ch.isdigit())
    if len(cleaned) != 6:
        return False

    current_time = int(time.time())
    for offset in range(-window, window + 1):
        candidate_time = current_time + (offset * interval)
        if hmac.compare_digest(get_totp_token(secret, for_time=candidate_time, interval=interval), cleaned):
            return True
    return False