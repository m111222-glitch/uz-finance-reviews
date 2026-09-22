"""Xiaomi GetApps scraper (best-effort public market endpoints)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

# GetApps / Mi Market hosts that have historically exposed JSON
SEARCH_URLS = [
    "https://app.market.xiaomi.com/apm/search",
]
COMMENT_URLS = [
    "https://app.market.xiaomi.com/apm/comment/parentcommentlist",
    "https://app.market.xiaomi.com/apm/comment/parentCommentList",
]

DEVICE = {
    "os": "1",
    "sdk": "33",
    "la": "ru",
    "co": "UZ",
    "ua": "POCO F5",
    "deviceType": "0",
    "version": "40001000",
}


def _iso_ms(value: Any) -> str | None:
    if value is None:
        return None
    try:
        n = int(value)
        if n > 10_000_000_000:
            n = n / 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value)


def fetch_xiaomi_meta(package: str) -> dict[str, Any]:
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; 2201117TY MIUI/V14)",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
        r = client.get(SEARCH_URLS[0], params={**DEVICE, "keywords": package, "page": 0})
        if r.status_code != 200:
            return {"xiaomi_rating": None, "meta": {"package": package, "error": r.text[:200]}}
        try:
            data = r.json()
        except Exception:
            return {"xiaomi_rating": None, "meta": {"package": package}}
    apps = (
        data.get("listApp")
        or data.get("list")
        or data.get("data")
        or data.get("appList")
        or []
    )
    hit = None
    for item in apps:
        if not isinstance(item, dict):
            continue
        if (item.get("packageName") or item.get("package") or "") == package:
            hit = item
            break
    if not hit and apps:
        hit = apps[0] if isinstance(apps[0], dict) else None
    if not hit:
        return {"xiaomi_rating": None, "meta": {"package": package}}
    rating = hit.get("ratingScore") or hit.get("score") or hit.get("star")
    try:
        rating_f = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating_f = None
    return {
        "xiaomi_rating": rating_f,
        "icon_url": hit.get("icon") or hit.get("iconUrl"),
        "meta": {
            "title": hit.get("displayName") or hit.get("name"),
            "package": package,
            "appId": hit.get("appId") or hit.get("id"),
            "version": hit.get("versionName"),
        },
    }


def fetch_xiaomi_reviews(package: str, app_slug: str, *, count: int = 80) -> list[dict[str, Any]]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; 2201117TY MIUI/V14)",
        "Accept": "application/json",
    }
    comments: list[dict[str, Any]] = []
    with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
        for url in COMMENT_URLS:
            try:
                r = client.get(
                    url,
                    params={
                        **DEVICE,
                        "packageName": package,
                        "page": 0,
                        "pageIndex": 0,
                        "n": min(count, 50),
                    },
                )
            except Exception:
                continue
            if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
                continue
            try:
                data = r.json()
            except Exception:
                continue
            lst = (
                data.get("list")
                or data.get("comments")
                or data.get("commentList")
                or (data.get("data") or {}).get("list")
                or []
            )
            if isinstance(lst, list) and lst:
                comments = [x for x in lst if isinstance(x, dict)]
                break
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(comments[:count]):
        body = (item.get("comment") or item.get("content") or item.get("text") or "").strip()
        if not body:
            continue
        cid = item.get("commentId") or item.get("id") or f"{package}:{i}:{body[:30]}"
        try:
            rating = int(float(item.get("score") or item.get("star") or item.get("rating") or 0))
        except (TypeError, ValueError):
            rating = None
        rows.append(
            {
                "id": f"xiaomi:{cid}",
                "app_slug": app_slug,
                "store": "xiaomi",
                "author": item.get("nickname") or item.get("userName") or "Anonymous",
                "rating": rating if rating and 1 <= rating <= 5 else None,
                "title": item.get("title"),
                "body": body,
                "language": "ru",
                "version": item.get("versionName") or item.get("version"),
                "thumbs_up": int(item.get("likeCount") or item.get("likes") or 0),
                "review_date": _iso_ms(item.get("updateTime") or item.get("createTime") or item.get("time")),
                "scraped_at": scraped_at,
                "raw_json": json.dumps(item, ensure_ascii=False, default=str),
            }
        )
    return rows
