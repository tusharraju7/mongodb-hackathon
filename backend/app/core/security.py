"""Identity: password hashing, tokens, the request identity, and step-up verification.

The identity always comes from the signed token. It is never read from a request body and never
from model output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, Query

from app.core.config import get_settings
from app.core.db import get_db, oid
from app.models import Identity

TOKEN_HOURS = 12
ALGORITHM = "HS256"


class StepUpFailed(Exception):
    """The password given to confirm a sensitive change was missing or wrong."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def password_matches(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET is not set. Add it to .env; the whole team must use the same value.")
    return secret


def issue_token(identity: Identity) -> str:
    now = datetime.now(timezone.utc)
    claims = {**identity.model_dump(), "sub": identity.user_id, "iat": now, "exp": now + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def identity_from_token(token: str) -> Identity:
    claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    return Identity(**{k: claims[k] for k in ("user_id", "email", "name", "role", "team")})


def current_identity(authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)) -> Identity:
    """FastAPI dependency. Accepts a bearer header, or a `token` query parameter for <audio>, <img> and EventSource."""
    raw = token
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        return identity_from_token(raw)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def authenticate(email: str, password: str, db=None) -> Optional[Identity]:
    db = db if db is not None else get_db()
    user = db.users.find_one({"email": email.strip().lower()})
    if not user or not password_matches(password, user.get("password_hash", "")):
        return None
    return Identity(user_id=str(user["_id"]), email=user["email"], name=user.get("name", ""), role=user["role"], team=user["team"])


def verify_password(identity: Identity, password: Optional[str], db=None) -> bool:
    """Step-up check, asked on every sensitive change. The password is compared and then discarded."""
    if not password:
        return False
    db = db if db is not None else get_db()
    user = db.users.find_one({"_id": oid(identity.user_id)}) or db.users.find_one({"email": identity.email})
    return bool(user) and password_matches(password, user.get("password_hash", ""))


def require_step_up(identity: Identity, password: Optional[str], db=None) -> str:
    """Returns the auth method to record on the ledger, or raises StepUpFailed."""
    if not verify_password(identity, password, db):
        raise StepUpFailed("This change needs your password, and the one given was missing or wrong.")
    return "jwt+password"
