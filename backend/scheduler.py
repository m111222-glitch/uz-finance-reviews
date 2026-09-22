"""Background auto-sync so store reviews refresh without a button click."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend import db


def auto_sync_hours() -> float:
    raw = os.getenv("AUTO_SYNC_HOURS", "3").strip()
    try:
        hours = float(raw)
    except ValueError:
        hours = 3.0
    return max(hours, 0.0)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def hours_since_last_ok_sync() -> float | None:
    row = db.last_successful_sync()
    finished = _parse_iso((row or {}).get("finished_at") or (row or {}).get("started_at"))
    if not finished:
        return None
    now = datetime.now(timezone.utc)
    return max((now - finished).total_seconds() / 3600.0, 0.0)


def next_sync_at_iso(interval_hours: float) -> str | None:
    if interval_hours <= 0:
        return None
    row = db.last_successful_sync()
    finished = _parse_iso((row or {}).get("finished_at") or (row or {}).get("started_at"))
    if not finished:
        return datetime.now(timezone.utc).isoformat()
    return (finished + timedelta(hours=interval_hours)).isoformat()


def status_payload() -> dict[str, Any]:
    hours = auto_sync_hours()
    since = hours_since_last_ok_sync()
    return {
        "enabled": hours > 0,
        "interval_hours": hours,
        "hours_since_last_ok": round(since, 2) if since is not None else None,
        "next_sync_at": next_sync_at_iso(hours) if hours > 0 else None,
    }


def start_auto_sync_loop(run_sync: Callable[[], None]) -> None:
    """Daemon loop: sync if stale, then sleep for the remaining interval."""

    hours = auto_sync_hours()
    if hours <= 0:
        print("AUTO_SYNC_HOURS=0 — scheduled sync disabled")
        return

    interval_sec = hours * 3600.0

    def _loop() -> None:
        # Short delay so the HTTP server is up first
        threading.Event().wait(15)
        while True:
            since = hours_since_last_ok_sync()
            due = since is None or since >= hours
            if due:
                print(f"Auto-sync starting (hours since last ok: {since})")
                try:
                    run_sync()
                except Exception as exc:
                    print(f"Auto-sync failed: {exc}")
                wait = interval_sec
            else:
                wait = max((hours - (since or 0)) * 3600.0, 60.0)
                print(f"Auto-sync sleeping {wait / 3600:.2f}h until next run")
            threading.Event().wait(wait)

    threading.Thread(target=_loop, name="auto-sync", daemon=True).start()
    print(f"Auto-sync enabled every {hours:g} hours")
