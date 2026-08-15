from __future__ import annotations

import asyncio
import hashlib
import secrets

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()
_dummy_password_hash = _password_hash.hash("infoscope-dummy-password")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_password_hash.hash, password)


async def verify_password(password: str, encoded_hash: str | None) -> bool:
    candidate_hash = encoded_hash or _dummy_password_hash
    verified = await asyncio.to_thread(_password_hash.verify, password, candidate_hash)
    return encoded_hash is not None and verified


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
