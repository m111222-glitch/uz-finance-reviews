"""Track store builds and post their release notes to a separate Telegram channel."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from backend import db, notify

STORE_NAMES = {
    "ios": "🍎 App Store",
    "play": "🤖 Google Play",
    "huawei": "🌺 AppGallery",
    "xiaomi": "🟧 GetApps",
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
    elif store == "xiaomi":
        # GetApps pages carry no changelog; notes are borrowed from Play below
        out = {
            "version": _version(meta.get("version")),
            "released_at": _utc_iso(meta.get("updated_at")),
            "notes": None,
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
        if rel and store == "xiaomi" and rel["version"]:
            # Xiaomi ships the same APK as Play, usually a version or two behind
            rel["notes"] = db.release_notes(slug, "play", rel["version"])
        if rel and db.record_release(slug, store, app_name=app_name, **rel):
            new += 1
    return new


def sync_release_only_apps(
    apps: list[dict[str, Any]], *, country: str, lang: str
) -> dict[str, Any]:
    """Shops etc. we follow for release notes only — no reviews, no dashboard row."""
    from backend.scrapers import appstore, huawei, play, xiaomi

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
        if app.get("huawei_id"):
            try:
                meta_blob["huawei"] = huawei.fetch_huawei_meta(app["huawei_id"]).get("meta") or {}
            except Exception as exc:
                stats["errors"].append(f"{app['slug']}/huawei: {exc}")
        xiaomi_pkg = app.get("xiaomi_id") or app.get("play_id")
        if xiaomi_pkg:
            try:
                xmeta = xiaomi.fetch_xiaomi_meta(xiaomi_pkg).get("meta") or {}
                if not xmeta.get("error"):
                    meta_blob["xiaomi"] = xmeta
            except Exception as exc:
                stats["errors"].append(f"{app['slug']}/xiaomi: {exc}")
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


def format_release(rel: dict[str, Any]) -> str:
    app = rel.get("display_name") or rel.get("app_name") or rel["app_slug"]
    store = STORE_NAMES.get(rel["store"], rel["store"])
    version = rel.get("version")
    head = f"🚀 {notify.app_emoji(rel['app_slug'])}<b>{notify._esc(app)}</b>" + (
        f" {notify._esc(version)}" if version else ""
    )
    date = notify._tashkent_date(rel.get("released_at") or rel.get("first_seen_at"))
    lines = [head, f"{store} · {date}", ""]
    notes = (rel.get("notes") or "").strip()
    if notes:
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
        text = format_release(rel)
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


# ---- Monthly recap: who shipped how often, and how releases were received

MONTH_STORES = ("ios", "play")  # Huawei/GetApps mirror Play builds late
HIGHLIGHT_SLUG = "alif-mobi"
TOP_FREQUENT = 3
TOP_COMPLAINTS = 5
RU_MONTHS_PREP = (
    "январе", "феврале", "марте", "апреле", "мае", "июне",
    "июле", "августе", "сентябре", "октябре", "ноябре", "декабре",
)


def _dt(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=notify.TASHKENT)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=notify.TASHKENT)
    return start, end


def month_stats(year: int, month: int) -> list[dict[str, Any]]:
    """Per app and store: builds released that month, average gap, 1–2★ on them.

    Stores are counted apart because iOS and Play version numbers often differ.
    The gap includes the step from the previous month's last build.
    """
    start, end = _month_range(year, month)
    catalog = db.load_catalog()
    full = {a["slug"] for a in catalog["apps"]}
    out = []
    for app in catalog["apps"] + (catalog.get("release_only_apps") or []):
        slug = app["slug"]
        row: dict[str, Any] = {"slug": slug, "name": app["name"], "full": slug in full}
        negatives = 0
        rated = 0
        for store in MONTH_STORES:
            builds = db.store_releases(slug, store)
            idx = [i for i, b in enumerate(builds) if start <= _dt(b["released_at"]) < end]
            gaps = [
                (_dt(builds[i]["released_at"]) - _dt(builds[i - 1]["released_at"])).total_seconds() / 86400
                for i in idx
                if i > 0
            ]
            neg = 0
            for i in idx:
                version = builds[i]["version"]
                if slug in full and version:
                    neg += db.negative_reviews_on_version(slug, store, version)
                    rated += 1
            negatives += neg
            row[store] = {
                "n": len(idx),
                "gap": sum(gaps) / len(gaps) if gaps else None,
                "neg": neg,
            }
        row["negatives"] = negatives
        row["neg_per_release"] = negatives / rated if rated else None
        out.append(row)
    return out


def _days(gap: float | None) -> str:
    if gap is None:
        return ""
    d = max(1, round(gap))
    if d == 1:
        return "каждый день"
    return f"раз в {d} {notify._ru_plural(d, 'день', 'дня', 'дней')}"


def _store_part(store: str, s: dict[str, Any]) -> str:
    icon = STORE_NAMES[store].split(" ", 1)[0]
    n = s["n"]
    text = f"{icon} {n} {notify._ru_plural(n, 'релиз', 'релиза', 'релизов')}"
    return text + (f" ({_days(s['gap'])})" if n and s["gap"] is not None else "")


def _decimal(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def format_month_summary(year: int, month: int, stats: list[dict[str, Any]]) -> str:
    esc = notify._esc
    lines = [
        f"📅 <b>Итоги {notify.RU_MONTHS[month - 1]} {year}</b>",
        "Релизы в App Store и Google Play",
        "",
    ]

    frequent = sorted(
        (r for r in stats if r["ios"]["n"] or r["play"]["n"]),
        key=lambda r: (-max(r["ios"]["n"], r["play"]["n"]), -(r["ios"]["n"] + r["play"]["n"])),
    )[:TOP_FREQUENT]
    if frequent:
        lines.append("🏃 <b>Чаще всех выпускались</b>")
        for r in frequent:
            parts = " · ".join(_store_part(st, r[st]) for st in MONTH_STORES if r[st]["n"])
            lines.append(f"• {notify.app_emoji(r['slug'])}{esc(r['name'])} — {parts}")
        lines.append("")

    hl = next((r for r in stats if r["slug"] == HIGHLIGHT_SLUG), None)
    if hl:
        parts = " · ".join(_store_part(st, hl[st]) for st in MONTH_STORES)
        lines += [f"🔷 {notify.app_emoji(hl['slug'])}<b>{esc(hl['name'])}</b> — {parts}", ""]

    complained = sorted(
        (r for r in stats if r["neg_per_release"]),
        key=lambda r: -r["neg_per_release"],
    )[:TOP_COMPLAINTS]
    if complained:
        lines.append("😠 <b>Больше всего жалоб на релиз</b>")
        lines.append("<i>отзывы на 1–2★, оставленные на новой версии</i>")
        for r in complained:
            lines.append(
                f"• {notify.app_emoji(r['slug'])}{esc(r['name'])} — {_decimal(r['neg_per_release'])}"
            )
        total = sum(r["negatives"] for r in complained)
        play = sum(r["play"]["neg"] for r in complained)
        if total and play / total >= 0.7:
            lines.append(
                f"{round(100 * play / total)}% этих жалоб — из Google Play: там отзывов в разы больше."
            )
        lines.append("")

    silent = [r["name"] for r in stats if not r["ios"]["n"] and not r["play"]["n"]]
    if silent:
        lines.append(f"🔕 <b>Без релизов в {RU_MONTHS_PREP[month - 1]}</b>")
        lines.append(esc(", ".join(silent)))
        lines.append("")

    lines.append("#итоги_месяца")
    return "\n".join(lines).strip()


def maybe_post_month_summary(*, dry_run: bool = False) -> dict[str, Any]:
    """Once per month, after the 1st: last month's release recap."""
    today = datetime.now(notify.TASHKENT).date()
    last = today.replace(day=1) - timedelta(days=1)
    key = f"releases-{last.year}-{last.month:02d}"
    out: dict[str, Any] = {"month": key, "posted": False, "skipped": False}
    start, _ = _month_range(last.year, last.month)
    seen = db.earliest_release_seen()
    # Tracking must have started by the month's first days, or counts are partial
    if not seen or _dt(seen) > start + timedelta(days=3) or db.summary_posted(key):
        out["skipped"] = True
        return out
    stats = month_stats(last.year, last.month)
    out["preview"] = format_month_summary(last.year, last.month, stats)
    if dry_run or not enabled():
        return out
    notify.send_message(out["preview"], chat_id=chat_id())
    db.mark_summary_posted(key, {s["slug"]: [s["ios"]["n"], s["play"]["n"]] for s in stats})
    out["posted"] = True
    return out
