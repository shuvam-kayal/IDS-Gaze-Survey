"""Environment-provisioned researcher authentication and server-side roles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Response, status

SESSION_COOKIE = "ids_researcher_session"
CSRF_COOKIE = "ids_researcher_csrf"
SESSION_SECONDS = 8 * 60 * 60
PBKDF2_ITERATIONS = 310_000


class Role(StrEnum):
    ADMIN = "admin"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(StrEnum):
    VIEW_EXPERIENCES = "experiences:view"
    MANAGE_EXPERIENCES = "experiences:manage"
    VIEW_STUDIES = "studies:view"
    CREATE_STUDIES = "studies:create"
    EDIT_STUDIES = "studies:edit"
    PUBLISH_STUDIES = "studies:publish"
    ARCHIVE_STUDIES = "studies:archive"
    EXPORT_RESULTS = "results:export"
    MANAGE_USERS = "users:manage"


ALL_PERMISSIONS = frozenset(Permission)
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: ALL_PERMISSIONS,
    Role.RESEARCHER: frozenset(
        {
            Permission.VIEW_EXPERIENCES,
            Permission.MANAGE_EXPERIENCES,
            Permission.VIEW_STUDIES,
            Permission.CREATE_STUDIES,
            Permission.EDIT_STUDIES,
            Permission.PUBLISH_STUDIES,
            Permission.ARCHIVE_STUDIES,
        }
    ),
    Role.ANALYST: frozenset(
        {Permission.VIEW_EXPERIENCES, Permission.VIEW_STUDIES, Permission.EXPORT_RESULTS}
    ),
    Role.VIEWER: frozenset({Permission.VIEW_EXPERIENCES, Permission.VIEW_STUDIES}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: Role
    csrf_token: str
    display_name: str


@dataclass(frozen=True)
class UserCredential:
    username: str
    user_id: str
    role: Role
    password_hash: str
    display_name: str


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Create a password hash for offline operator provisioning."""
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= iterations <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _decode_base64(salt_text), iterations
        )
        return hmac.compare_digest(actual, _decode_base64(digest_text))
    except (ValueError, TypeError):
        return False


def valid_password_hash(encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        salt, digest = _decode_base64(salt_text), _decode_base64(digest_text)
        return algorithm == "pbkdf2_sha256" and 100_000 <= iterations <= 2_000_000 and len(salt) >= 16 and len(digest) == 32
    except (ValueError, TypeError):
        return False


def load_credentials() -> dict[str, UserCredential]:
    raw = os.getenv("CONTROL_PLANE_USERS_JSON", "")
    if not raw:
        return {}
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("CONTROL_PLANE_USERS_JSON must be valid JSON") from exc
    if not isinstance(entries, list):
        raise RuntimeError("CONTROL_PLANE_USERS_JSON must contain a list")
    credentials: dict[str, UserCredential] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Each researcher user must be an object")
        username = entry.get("username")
        user_id = entry.get("user_id")
        password_hash = entry.get("password_hash")
        display_name = entry.get("display_name", username)
        try:
            role = Role(entry.get("role"))
        except ValueError as exc:
            raise RuntimeError(f"Invalid role for researcher user {username!r}") from exc
        if (
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(user_id, str)
            or not user_id.strip()
            or not isinstance(password_hash, str)
            or not valid_password_hash(password_hash)
        ):
            raise RuntimeError("Researcher users need username, user_id, role, and a PBKDF2 password_hash")
        if username in credentials:
            raise RuntimeError(f"Duplicate researcher username {username!r}")
        credentials[username] = UserCredential(
            username=username,
            user_id=user_id,
            role=role,
            password_hash=password_hash,
            display_name=str(display_name),
        )
    return credentials


def _secret() -> bytes:
    value = os.getenv("CONTROL_PLANE_SECRET", "")
    if len(value.encode()) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Researcher authentication is not configured",
        )
    return value.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def issue_session(user: UserCredential, *, now: int | None = None) -> tuple[str, str, int]:
    csrf_token = secrets.token_urlsafe(32)
    issued_at = int(time.time() if now is None else now)
    claims = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role.value,
        "display_name": user.display_name,
        "csrf": csrf_token,
        "iat": issued_at,
        "exp": issued_at + SESSION_SECONDS,
    }
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}", csrf_token, SESSION_SECONDS


def _read_session(token: str | None) -> Principal:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        claims = json.loads(_decode_base64(payload))
        if int(claims["exp"]) <= int(time.time()):
            raise ValueError("expired session")
        return Principal(
            user_id=claims["sub"],
            username=claims["username"],
            role=Role(claims["role"]),
            csrf_token=claims["csrf"],
            display_name=claims["display_name"],
        )
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def get_principal(
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal:
    return _read_session(token)


def require_permission(permission: Permission):
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if permission not in ROLE_PERMISSIONS[principal.role]:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return principal

    return dependency


def require_csrf(
    principal: Annotated[Principal, Depends(get_principal)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Principal:
    if not csrf_header or not hmac.compare_digest(csrf_header, principal.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")
    return principal


def set_session_cookies(response: Response, token: str, csrf_token: str, max_age: int) -> None:
    secure = os.getenv("CONTROL_PLANE_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    if not os.getenv("CONTROL_PLANE_COOKIE_SECURE"):
        secure = os.getenv("APP_ENV", "production").lower() != "development"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, samesite="strict")
