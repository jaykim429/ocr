"""인증 — bcrypt 비밀번호 해시 + JWT 토큰.

사용자 저장소는 chandra_api/users.json (없으면 기본 admin 생성). 운영 시 환경변수
QR_ADMIN_USER/QR_ADMIN_PASS, QR_JWT_SECRET 로 덮어쓴다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt

_USERS_PATH = Path(__file__).with_name("users.json")
_SECRET = os.environ.get("QR_JWT_SECRET", "dev-secret-change-me")
_ALGO = "HS256"
_TOKEN_HOURS = 12


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_pw(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


def _load_users() -> dict[str, Any]:
    if _USERS_PATH.exists():
        return json.loads(_USERS_PATH.read_text(encoding="utf-8"))
    # 기본 admin 생성 (운영 시 즉시 변경 권장)
    user = os.environ.get("QR_ADMIN_USER", "admin")
    pw = os.environ.get("QR_ADMIN_PASS", "changeme")
    users = {user: {"password_hash": hash_pw(pw), "role": "admin"}}
    _USERS_PATH.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    return users


def authenticate(username: str, password: str) -> bool:
    users = _load_users()
    rec = users.get(username)
    return bool(rec and verify_pw(password, rec["password_hash"]))


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_HOURS),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def decode_token(token: str) -> str | None:
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALGO]).get("sub")
    except Exception:  # noqa: BLE001
        return None
