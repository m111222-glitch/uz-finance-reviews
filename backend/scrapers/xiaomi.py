"""Xiaomi GetApps scraper.

The private, device-authenticated GetApps/Mi Market API
(``https://app.market.xiaomi.com/apm/search`` and
``.../apm/comment/parentcommentlist``) rejects every request with
``{"errDesc":"参数不合法","errCode":4}`` ("invalid parameters") regardless of
the app queried -- verified against both the catalog apps below and a
globally popular app (``com.whatsapp``). Those endpoints require a signed
request (HMAC device signature tied to a MIUI device/account token) that
Xiaomi does not publish; there is no legitimate way to derive it without
proprietary device credentials, so we do not attempt it.

Instead we scrape the public GetApps storefront page
(``https://global.app.mi.com/details?id=<package>``), which is server-rendered
(Nuxt.js) with the app's data embedded in a ``window.__NUXT__ = ...`` blob in
the HTML. This gives us real, unauthenticated data: rating, install count,
category, version, icon. Confirmed working against real catalog apps, e.g.
``uz.dida.payme`` (payme, 4.2 rating) and
``air.com.ssdsoftwaresolutions.clickuz`` (Click SuperApp, 4.3 rating). Not
every app is listed on GetApps -- a package that isn't returns HTTP 404,
which we treat as "no Xiaomi presence" rather than an error.

Crucially, this storefront page only exposes the *aggregate* rating score --
there is no individual review list, review text, author, or per-review date
anywhere on it or in any endpoint it calls (checked the rendered page,
network requests, and the page's own JS bundles for a comments/reviews API;
none exists). So ``fetch_xiaomi_reviews`` always returns an empty list --
that is expected, permanent behavior given what GetApps' public surface
exposes, not a silent failure to be confused with a bug.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

DETAILS_URL = "https://global.app.mi.com/details"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# The GetApps storefront only serves a handful of UI languages; "ru" 404s
# even for apps that otherwise exist there, but "en" is reliably supported
# and the fields we scrape (rating, counts, category) aren't language
# dependent, so we always request it in English.
LANG = "en"

_STR_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\(.)")


def _js_unescape(s: str) -> str:
    def repl(m: re.Match) -> str:
        if m.group(1):
            return chr(int(m.group(1), 16))
        ch = m.group(2)
        return {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "/": "/"}.get(ch, ch)

    return _STR_ESCAPE_RE.sub(repl, s)


def _extract_str(html: str, key: str) -> str | None:
    m = re.search(rf'{re.escape(key)}:"((?:\\.|[^"\\])*)"', html)
    return _js_unescape(m.group(1)) if m else None


def _extract_num(html: str, key: str) -> float | None:
    m = re.search(rf"{re.escape(key)}:(-?\d+(?:\.\d+)?)", html)
    return float(m.group(1)) if m else None


def _extract_rating(html: str) -> float | None:
    raw = _extract_str(html, "ratingScoreJson")
    if not raw:
        return _extract_num(html, "ratingScore")
    try:
        scores = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(scores, dict) or not scores:
        return None
    values = [v for v in scores.values() if isinstance(v, (int, float))]
    return float(values[0]) if values else None


def _iso_ms(value: Any) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
        if n > 10_000_000_000:
            n = n / 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_xiaomi_meta(package: str, *, country: str = "uz") -> dict[str, Any]:
    params = {"id": package, "lo": country.upper(), "la": LANG}
    with httpx.Client(timeout=25.0, follow_redirects=True, headers=HEADERS) as client:
        r = client.get(DETAILS_URL, params=params)
        if r.status_code == 404:
            return {"xiaomi_rating": None, "meta": {"package": package, "error": "not_found"}}
        if r.status_code != 200:
            return {
                "xiaomi_rating": None,
                "meta": {"package": package, "error": f"http_{r.status_code}"},
            }
        html = r.text

    if _extract_str(html, "packageName") != package:
        # Storefront fell back to a generic/home page instead of the app.
        return {"xiaomi_rating": None, "meta": {"package": package, "error": "not_found"}}

    icon_path = _extract_str(html, "icon")
    thumbnail_base = _extract_str(html, "thumbnail")
    icon_url = f"{thumbnail_base}{icon_path}" if icon_path and thumbnail_base else None

    return {
        "xiaomi_rating": _extract_rating(html),
        "icon_url": icon_url,
        "meta": {
            "title": _extract_str(html, "displayName"),
            "package": package,
            "developer": _extract_str(html, "developerName") or _extract_str(html, "publisherName"),
            "version": _extract_str(html, "versionName"),
            "category": _extract_str(html, "level1CategoryName"),
            "install_count": _extract_num(html, "downloadCount"),
            "apk_size_bytes": _extract_num(html, "apkSize"),
            "updated_at": _iso_ms(_extract_num(html, "updateTime")),
        },
    }


def fetch_xiaomi_reviews(package: str, app_slug: str, *, count: int = 80) -> list[dict[str, Any]]:
    """Always returns [] -- see module docstring: GetApps' public storefront
    exposes only an aggregate rating, never individual review text, and the
    private review API is unreachable without a proprietary device signature.
    """
    return []
