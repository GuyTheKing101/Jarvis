import hmac
import hashlib
import base64
import os
import secrets
from typing import Optional

_SESSIONS: dict[str, int] = {}

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return base64.b64encode(salt + digest).decode("utf-8")

def verify_password(password: str, stored: str) -> bool:
    raw = base64.b64decode(stored.encode("utf-8"))
    salt, digest = raw[:16], raw[16:]
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(digest, check)

def create_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = user_id
    return token

def get_user_id_from_token(token: str):
    return _SESSIONS.get(token)
