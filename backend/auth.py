"""Optional password gate for shared dashboard access."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE_NAME = "uz_finance_auth"

# Always public when password gate is on
PUBLIC_EXACT = {
    "/api/health",
    "/api/login",
    "/api/logout",
    "/api/auth/status",
    "/login",
    "/assets/login.css",
    "/assets/login.js",
}


def password_enabled() -> bool:
    return bool(os.getenv("DASHBOARD_PASSWORD", "").strip())


def get_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "").strip()


def readonly_mode() -> bool:
    return os.getenv("DASHBOARD_READONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _secret() -> str:
    return os.getenv("DASHBOARD_SECRET", "uz-finance-reviews-dev-secret").strip()


def session_token() -> str:
    """Stable token derived from password + secret (survives restarts)."""
    raw = f"{get_password()}|{_secret()}"
    return hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()


def verify_password(candidate: str) -> bool:
    expected = get_password()
    if not expected:
        return True
    return secrets.compare_digest(candidate.strip(), expected)


def request_authenticated(request: Request) -> bool:
    if not password_enabled():
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    return bool(cookie) and secrets.compare_digest(cookie, session_token())


class PasswordGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not password_enabled():
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_EXACT:
            return await call_next(request)

        if request_authenticated(request):
            if (
                readonly_mode()
                and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
                and path.startswith("/api/sync")
            ):
                return JSONResponse(
                    {"detail": "Dashboard is read-only for shared viewers"},
                    status_code=403,
                )
            return await call_next(request)

        accept = request.headers.get("accept", "")
        if path.startswith("/api/"):
            return JSONResponse(
                {"detail": "Unauthorized", "login": "/login"},
                status_code=401,
            )
        if "text/html" in accept or not path.startswith("/assets/"):
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
