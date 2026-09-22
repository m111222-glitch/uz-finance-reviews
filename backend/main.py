"""FastAPI app: Uzbekistan finance category review dashboard."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import analytics, auth, db, notify, scheduler
from backend.sync import sync_all

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="UZ Finance Reviews",
    description="Review dashboard for Uzbekistan finance apps on Play Store & App Store",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.add_middleware(auth.PasswordGateMiddleware)

_sync_lock = threading.Lock()
_sync_state: dict[str, Any] = {"running": False, "last_result": None}


def _run_sync(*, slug: str | None = None, play_count: int = 150, ios_pages: int = 5) -> dict[str, Any]:
    with _sync_lock:
        if _sync_state["running"]:
            return {"status": "already_running"}
        _sync_state["running"] = True
        try:
            result = sync_all(
                play_review_count=play_count,
                ios_pages=ios_pages,
                only_slug=slug,
            )
            _sync_state["last_result"] = result
            return result
        finally:
            _sync_state["running"] = False


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    db.upsert_apps_from_catalog()
    scheduler.start_auto_sync_loop(lambda: _run_sync())


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "auth_required": auth.password_enabled(),
        "readonly": auth.readonly_mode(),
        "auto_sync": scheduler.status_payload(),
        "telegram": notify.enabled(),
    }


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    return {
        "auth_required": auth.password_enabled(),
        "authenticated": auth.request_authenticated(request),
        "readonly": auth.readonly_mode(),
    }


@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    if not auth.password_enabled():
        return {"ok": True, "auth_required": False}
    if not auth.verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")

    env_secure = os.getenv("DASHBOARD_COOKIE_SECURE", "").lower()
    if env_secure in {"1", "true", "yes"}:
        secure = True
    elif env_secure in {"0", "false", "no"}:
        secure = False
    else:
        # Auto: HTTPS (incl. Cloudflare tunnel) gets Secure cookies; local HTTP does not
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        secure = proto == "https"

    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=auth.session_token(),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=60 * 60 * 24 * 14,  # 14 days
        path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": "logged_out"}


@app.get("/api/dashboard")
def dashboard(
    app: str | None = Query(None, description="App slug"),
    store: str | None = Query(None, pattern="^(play|ios|huawei|xiaomi)$"),
) -> dict[str, Any]:
    stats = db.dashboard_stats(app_slug=app, store=store)
    return analytics.enrich_dashboard(stats)


@app.get("/api/apps")
def list_apps() -> list[dict[str, Any]]:
    return db.get_apps()


@app.get("/api/apps/{slug}")
def get_app(slug: str) -> dict[str, Any]:
    row = db.get_app(slug)
    if not row:
        raise HTTPException(404, f"App not found: {slug}")
    reviews, total = db.query_reviews(app_slug=slug, limit=30)
    row["recent_reviews"] = reviews
    row["total_reviews"] = total
    return row


@app.get("/api/reviews")
def list_reviews(
    app: str | None = Query(None, description="App slug"),
    store: str | None = Query(None, pattern="^(play|ios|huawei|xiaomi)$"),
    rating: int | None = Query(None, ge=1, le=5),
    q: str | None = Query(None, description="Search text"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = db.query_reviews(
        app_slug=app,
        store=store,
        rating=rating,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/telegram/preview")
def telegram_preview(limit: int = Query(15, ge=1, le=50)) -> dict[str, Any]:
    """Show which 1★/5★ reviews would be posted (short/generic ones excluded)."""
    db.init_db()
    rows = notify.preview_candidates(limit=limit)
    return {
        "enabled": notify.enabled(),
        "count": len(rows),
        "items": [
            {
                "id": r.get("id"),
                "app_name": r.get("app_name"),
                "store": r.get("store"),
                "rating": r.get("rating"),
                "author": r.get("author"),
                "review_date": r.get("review_date"),
                "body": (r.get("body") or "")[:400],
            }
            for r in rows
        ],
    }


@app.get("/api/sync/status")
def sync_status() -> dict[str, Any]:
    return {
        "running": _sync_state["running"],
        "last_result": _sync_state["last_result"],
        "readonly": auth.readonly_mode(),
        "auto_sync": scheduler.status_payload(),
    }


@app.post("/api/sync")
def trigger_sync(
    background: bool = Query(True),
    slug: str | None = Query(None),
    play_count: int = Query(150, ge=20, le=500),
    ios_pages: int = Query(5, ge=1, le=10),
) -> dict[str, Any]:
    if auth.readonly_mode():
        raise HTTPException(403, "Dashboard is read-only for shared viewers")
    if _sync_state["running"]:
        return {"status": "already_running"}

    if background:
        threading.Thread(
            target=_run_sync,
            kwargs={"slug": slug, "play_count": play_count, "ios_pages": ios_pages},
            daemon=True,
        ).start()
        return {"status": "started"}
    result = _run_sync(slug=slug, play_count=play_count, ios_pages=ios_pages)
    return {"status": "done", "result": result}


@app.get("/login", response_class=HTMLResponse)
def login_page() -> FileResponse:
    path = FRONTEND / "login.html"
    if not path.exists():
        raise HTTPException(404, "Login page missing")
    return FileResponse(path)


# Static dashboard
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Dashboard UI not found")
    return FileResponse(index_path)
