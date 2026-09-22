"""Huawei AppGallery scraper (overseas Hispace web API)."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

CODE_URL = "https://web-dra.hispace.dbankcloud.com/webedge/getInterfaceCode"
API_URL = "https://web-dra.hispace.dbankcloud.com/uowap/index"
APP_ID_RE = re.compile(r"C\d{5,}")


def _open() -> httpx.Client:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://appgallery.huawei.com",
        "Referer": "https://appgallery.huawei.com/",
    }
    c = httpx.Client(timeout=30.0, follow_redirects=True, headers=headers)
    _refresh_code(c)
    return c


def _refresh_code(client: httpx.Client) -> None:
    r = client.get(CODE_URL)
    r.raise_for_status()
    code = r.json()
    if not isinstance(code, str):
        code = str(code)
    client.headers["Interface-Code"] = f"{code}_{int(time.time() * 1000)}"


def _get(client: httpx.Client, **params: Any) -> dict[str, Any]:
    base = {
        "method": "internal.getTabDetail",
        "serviceType": "20",
        "locale": "ru_RU",
        # Without an explicit zone AppGallery answers for the caller's IP region,
        # which on the (EU-hosted) server hides Uzbekistan ratings and reviews
        "zone": "UZ",
        "reqPageNum": "1",
        "maxResults": "25",
    }
    base.update({k: v for k, v in params.items() if v is not None})
    r = client.get(API_URL, params=base)
    if r.status_code == 403:
        _refresh_code(client)
        r = client.get(API_URL, params=base)
    r.raise_for_status()
    return r.json()


def _app_id_from_item(item: dict[str, Any]) -> str | None:
    for key in ("appid", "appId", "id"):
        val = item.get(key)
        if isinstance(val, str) and APP_ID_RE.fullmatch(val):
            return val
    blob = str(item.get("detailId") or item.get("id") or "")
    m = APP_ID_RE.search(blob)
    return m.group(0) if m else None


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def search_app(query: str, *, package: str | None = None, name: str | None = None) -> str | None:
    """Return AppGallery C-id for a name/package, or None if no confident match.

    AppGallery's search falls back to loosely-related global results when it has
    nothing relevant (common for small regional fintech apps), so a match is only
    accepted when the candidate's own package or name actually corresponds to the
    app we're looking for — otherwise we'd silently attribute another app's
    rating/reviews to this one.
    """
    client = _open()
    try:
        data = _get(client, uri=f"searchApp|{query}", currentUrl=f"https://appgallery.huawei.com/#/search/{query}")
        target_name = _normalize_name(name)
        for block in data.get("layoutData") or []:
            for item in block.get("dataList") or []:
                if not isinstance(item, dict):
                    continue
                appid = _app_id_from_item(item)
                if not appid:
                    continue
                if package and item.get("package") == package:
                    return appid
                if target_name and _normalize_name(item.get("name")) == target_name:
                    return appid
        return None
    finally:
        client.close()


def fetch_huawei_meta(app_id: str) -> dict[str, Any]:
    client = _open()
    try:
        data = _get(
            client,
            uri=f"app|{app_id}",
            appid=app_id,
            currentUrl=f"https://appgallery.huawei.com/app/{app_id}",
        )
    finally:
        client.close()
    name = None
    package = None
    stars = None
    installs = None
    icon = None
    developer = None
    version = None
    for block in data.get("layoutData") or []:
        for item in block.get("dataList") or []:
            if not isinstance(item, dict):
                continue
            name = name or item.get("name")
            package = package or item.get("package")
            if item.get("stars") is not None:
                try:
                    stars = float(item["stars"])
                except (TypeError, ValueError):
                    pass
            installs = installs or item.get("intro")
            icon = icon or item.get("icoUri")
            developer = developer or item.get("developer")
            version = version or item.get("version")
    return {
        "huawei_rating": stars,
        "icon_url": icon,
        "meta": {
            "title": name,
            "package": package,
            "developer": developer,
            "version": version,
            "installs": installs,
            "appid": app_id,
            "url": f"https://appgallery.huawei.com/app/{app_id}",
        },
    }


def _parse_hw_time(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y, %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return value


def fetch_huawei_reviews(app_id: str, app_slug: str) -> list[dict[str, Any]]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    client = _open()
    try:
        data = _get(
            client,
            uri=f"app|{app_id}",
            appid=app_id,
            currentUrl=f"https://appgallery.huawei.com/app/{app_id}",
        )
    finally:
        client.close()
    comments: list[dict[str, Any]] = []
    for block in data.get("layoutData") or []:
        if (block.get("layoutName") or "") not in {
            "pcscorecommentlistcard",
            "scorecommentlistcard",
            "commentlistcard",
        }:
            continue
        for wrap in block.get("dataList") or []:
            if not isinstance(wrap, dict):
                continue
            lst = wrap.get("list") or []
            for group in lst:
                if isinstance(group, dict) and "commentList" in group:
                    comments.extend(group.get("commentList") or [])
                elif isinstance(group, dict) and group.get("commentInfo"):
                    comments.append(group)
    seen: set[str] = set()
    for i, item in enumerate(comments):
        if not isinstance(item, dict):
            continue
        body = (item.get("commentInfo") or item.get("content") or "").strip()
        if not body:
            continue
        when = _parse_hw_time(item.get("commentTime") or item.get("operTime"))
        author = item.get("nickName") or item.get("userName") or "Anonymous"
        rid = f"huawei:{app_id}:{when or i}:{author}:{body[:40]}"
        if rid in seen:
            continue
        seen.add(rid)
        try:
            rating = int(float(item.get("stars") or item.get("rating") or 0))
        except (TypeError, ValueError):
            rating = None
        rows.append(
            {
                "id": rid,
                "app_slug": app_slug,
                "store": "huawei",
                "author": author,
                "rating": rating if rating and 1 <= rating <= 5 else None,
                "title": None,
                "body": body,
                "language": "ru",
                "version": item.get("version") or item.get("appVersion"),
                "thumbs_up": int(item.get("likeCount") or 0),
                "review_date": when,
                "scraped_at": scraped_at,
                "raw_json": json.dumps(item, ensure_ascii=False, default=str),
            }
        )
    return rows
