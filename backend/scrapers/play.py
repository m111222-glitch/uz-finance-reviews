"""Google Play Store scraper for Uzbekistan finance apps."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google_play_scraper import Sort, app as play_app, reviews as play_reviews


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def fetch_play_meta(app_id: str, *, country: str = "uz", lang: str = "ru") -> dict[str, Any]:
    data = play_app(app_id, lang=lang, country=country)
    return {
        "play_rating": data.get("score"),
        "play_ratings_count": data.get("ratings"),
        "play_installs": data.get("installs") or data.get("realInstalls"),
        "icon_url": data.get("icon"),
        "meta": {
            "title": data.get("title"),
            "developer": data.get("developer"),
            "genre": data.get("genre"),
            "url": data.get("url"),
            "updated": _iso(data.get("updated")),
            "version": data.get("version"),
            "free": data.get("free"),
            "containsAds": data.get("containsAds"),
            "reviews": data.get("reviews"),
            "histogram": data.get("histogram"),
            "description": (data.get("summary") or "")[:500],
        },
    }


def fetch_play_reviews(
    app_id: str,
    app_slug: str,
    *,
    country: str = "uz",
    lang: str = "ru",
    count: int = 200,
) -> list[dict[str, Any]]:
    result, _ = play_reviews(
        app_id,
        lang=lang,
        country=country,
        sort=Sort.NEWEST,
        count=count,
    )
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for item in result:
        review_id = item.get("reviewId") or item.get("id")
        if not review_id:
            continue
        rows.append(
            {
                "id": f"play:{review_id}",
                "app_slug": app_slug,
                "store": "play",
                "author": item.get("userName"),
                "rating": item.get("score"),
                "title": None,
                "body": item.get("content"),
                "language": lang,
                "version": item.get("reviewCreatedVersion") or item.get("appVersion"),
                "thumbs_up": item.get("thumbsUpCount") or 0,
                "review_date": _iso(item.get("at")),
                "scraped_at": scraped_at,
                "raw_json": json.dumps(item, default=str, ensure_ascii=False),
            }
        )
    return rows
