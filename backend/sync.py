"""Orchestrate metadata + review sync for catalog apps."""

from __future__ import annotations

import json
import traceback
from typing import Any

from backend import db
from backend.scrapers import appstore, play


def sync_all(
    *,
    play_review_count: int = 150,
    ios_pages: int = 5,
    only_slug: str | None = None,
) -> dict[str, Any]:
    db.init_db()
    db.upsert_apps_from_catalog()
    catalog = db.load_catalog()
    country = catalog.get("country", "uz")
    lang = catalog.get("language", "ru")

    run_id = db.start_sync_run()
    stats: dict[str, Any] = {
        "apps_ok": 0,
        "apps_failed": 0,
        "play_reviews": 0,
        "ios_reviews": 0,
        "errors": [],
    }

    apps = catalog["apps"]
    if only_slug:
        apps = [a for a in apps if a["slug"] == only_slug]

    try:
        for app in apps:
            slug = app["slug"]
            try:
                icon_url = None
                meta_blob: dict[str, Any] = {}

                if app.get("play_id"):
                    try:
                        pmeta = play.fetch_play_meta(
                            app["play_id"], country=country, lang=lang
                        )
                        icon_url = pmeta.get("icon_url") or icon_url
                        meta_blob["play"] = pmeta.get("meta") or {}
                        db.update_app_meta(
                            slug,
                            play_rating=pmeta.get("play_rating"),
                            play_ratings_count=pmeta.get("play_ratings_count"),
                            play_installs=str(pmeta.get("play_installs") or ""),
                        )
                        previews = play.fetch_play_reviews(
                            app["play_id"],
                            slug,
                            country=country,
                            lang=lang,
                            count=play_review_count,
                        )
                        # Also try uz language for more coverage
                        if lang != "uz":
                            previews_uz = play.fetch_play_reviews(
                                app["play_id"],
                                slug,
                                country=country,
                                lang="uz",
                                count=min(80, play_review_count),
                            )
                            seen = {r["id"] for r in previews}
                            for r in previews_uz:
                                if r["id"] not in seen:
                                    previews.append(r)
                        n = db.upsert_reviews(previews)
                        stats["play_reviews"] += len(previews)
                    except Exception as exc:
                        stats["errors"].append(f"{slug}/play: {exc}")

                if app.get("ios_id"):
                    try:
                        imeta = appstore.fetch_ios_meta(
                            app["ios_id"], country=country
                        )
                        icon_url = icon_url or imeta.get("icon_url")
                        meta_blob["ios"] = imeta.get("meta") or {}
                        db.update_app_meta(
                            slug,
                            ios_rating=imeta.get("ios_rating"),
                            ios_ratings_count=imeta.get("ios_ratings_count"),
                        )
                        ireviews = appstore.fetch_ios_reviews(
                            app["ios_id"],
                            slug,
                            country=country,
                            pages=ios_pages,
                        )
                        db.upsert_reviews(ireviews)
                        stats["ios_reviews"] += len(ireviews)
                    except Exception as exc:
                        stats["errors"].append(f"{slug}/ios: {exc}")

                db.update_app_meta(
                    slug,
                    icon_url=icon_url,
                    last_synced_at=db.utcnow(),
                    meta_json=json.dumps(meta_blob, ensure_ascii=False, default=str),
                )
                stats["apps_ok"] += 1
            except Exception as exc:
                stats["apps_failed"] += 1
                stats["errors"].append(f"{slug}: {exc}")

        db.finish_sync_run(run_id, status="ok", stats=stats)
        stats["run_id"] = run_id
        stats["status"] = "ok"
        return stats
    except Exception as exc:
        stats["errors"].append(str(exc))
        db.finish_sync_run(
            run_id,
            status="error",
            stats=stats,
            error=traceback.format_exc(),
        )
        stats["run_id"] = run_id
        stats["status"] = "error"
        return stats
