"""Track store builds and post their release notes to a separate Telegram channel."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from backend import db, notify

STORE_NAMES = {
    "ios": "🍎 App Store",
    "play": "🤖 Google Play",
    "huawei": "AppGallery",
}

# Play lists this instead of a version for apps with per-device builds
UNKNOWN_VERSIONS = {"", "varies with device", "зависит от устройства"}


def chat_id() -> str:
    return os.getenv("TELEGRAM_RELEASES_CHAT_ID", "").strip()


def enabled() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and chat_id())


def _utc_iso(value: Any) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _version(value: Any) -> str | None:
    v = str(value or "").strip()
    return None if v.lower() in UNKNOWN_VERSIONS else v


def extract(store: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    """Pull version / release time / notes out of one store's meta blob."""
    if store == "ios":
        out = {
            "version": _version(meta.get("version")),
            "released_at": _utc_iso(meta.get("currentVersionReleaseDate")),
            "notes": meta.get("releaseNotes"),
        }
    elif store == "play":
        out = {
            "version": _version(meta.get("version")),
            "released_at": _utc_iso(meta.get("updated")),
            "notes": meta.get("recentChanges"),
        }
    elif store == "huawei":
        out = {
            "version": _version(meta.get("version")),
            "released_at": _utc_iso(meta.get("releaseDate")),
            "notes": meta.get("releaseNotes"),
        }
    else:
        return None
    out["notes"] = (out["notes"] or "").strip() or None
    return out if (out["version"] or out["released_at"]) else None


def record_from_meta(
    slug: str, meta_blob: dict[str, Any], *, app_name: str | None = None
) -> int:
    new = 0
    for store, meta in meta_blob.items():
        rel = extract(store, meta or {})
        if rel and db.record_release(slug, store, app_name=app_name, **rel):
            new += 1
    return new


def sync_release_only_apps(
    apps: list[dict[str, Any]], *, country: str, lang: str
) -> dict[str, Any]:
    """Shops etc. we follow for release notes only — no reviews, no dashboard row."""
    from backend.scrapers import appstore, play

    stats: dict[str, Any] = {"new_releases": 0, "errors": []}
    for app in apps:
        meta_blob: dict[str, Any] = {}
        if app.get("play_id"):
            try:
                meta_blob["play"] = play.fetch_play_meta(
                    app["play_id"], country=country, lang=lang
                ).get("meta") or {}
            except Exception as exc:
                stats["errors"].append(f"{app['slug']}/play: {exc}")
        if app.get("ios_id"):
            try:
                meta_blob["ios"] = appstore.fetch_ios_meta(
                    app["ios_id"], country=country
                ).get("meta") or {}
            except Exception as exc:
                stats["errors"].append(f"{app['slug']}/ios: {exc}")
        try:
            stats["new_releases"] += record_from_meta(
                app["slug"], meta_blob, app_name=app["name"]
            )
        except Exception as exc:
            stats["errors"].append(f"{app['slug']}/releases: {exc}")
    return stats


def _hashtag(slug: str) -> str:
    # Slugs are unique, unlike first words of names ("Open…" is two apps)
    return "#" + slug.replace("-", "_")


def format_release(rel: dict[str, Any], *, same_notes_as: str | None = None) -> str:
    app = rel.get("display_name") or rel.get("app_name") or rel["app_slug"]
    store = STORE_NAMES.get(rel["store"], rel["store"])
    version = rel.get("version")
    head = f"🚀 <b>{notify._esc(app)}</b>" + (f" {notify._esc(version)}" if version else "")
    date = notify._tashkent_date(rel.get("released_at") or rel.get("first_seen_at"))
    lines = [head, f"{store} · {date}", ""]
    notes = (rel.get("notes") or "").strip()
    if same_notes_as:
        lines.append(f"Те же изменения, что и в {same_notes_as}.")
    elif notes:
        if len(notes) > 1500:
            notes = notes[:1490] + "…"
        lines.append(notify._esc(notes))
    else:
        lines.append("Описание изменений не указано.")
    lines += ["", _hashtag(rel["app_slug"])]
    return "\n".join(lines)


def post_new_releases(*, dry_run: bool = False) -> dict[str, Any]:
    stats: dict[str, Any] = {"enabled": enabled(), "posted": 0, "failed": 0, "errors": []}
    if not enabled() and not dry_run:
        return stats
    previews = []
    for rel in db.unposted_releases():
        same = None
        if rel.get("version"):
            for other in db.posted_release_notes(rel["app_slug"], rel["version"]):
                if other["store"] != rel["store"] and (other["notes"] or "") == (rel["notes"] or ""):
                    same = STORE_NAMES.get(other["store"], other["store"]).split(" ", 1)[-1]
                    break
        text = format_release(rel, same_notes_as=same)
        if dry_run:
            previews.append(text)
            continue
        try:
            notify.send_message(text, chat_id=chat_id())
            db.mark_release_posted(rel["app_slug"], rel["store"], rel["release_key"])
            stats["posted"] += 1
            time.sleep(3.1)  # Telegram allows ~20 msgs/min to one chat
        except Exception as exc:
            stats["errors"].append(f"{rel['app_slug']}/{rel['store']}: {notify._redact(str(exc))}")
            stats["failed"] += 1
            if stats["failed"] >= 3:
                break
    if dry_run:
        stats["previews"] = previews
    return stats
