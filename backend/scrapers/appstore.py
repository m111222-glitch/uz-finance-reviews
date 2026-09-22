"""Apple App Store scraper via public iTunes / RSS endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
RSS_CUSTOMER_REVIEWS = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "id={app_id}/sortBy=mostRecent/json"
)


def _rss_label(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        label = node.get("label")
        return str(label) if label is not None else None
    return str(node)


def _iso_from_rss(value: str | None) -> str | None:
    if not value:
        return None
    # RSS dates look like: 2024-05-12T10:11:12-07:00
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
    except ValueError:
        return value


def fetch_ios_meta(app_id: str, *, country: str = "uz") -> dict[str, Any]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(
            ITUNES_LOOKUP,
            params={"id": app_id, "country": country},
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            # Fallback: app may not be country-listed under UZ — try US
            resp = client.get(ITUNES_LOOKUP, params={"id": app_id, "country": "us"})
            resp.raise_for_status()
            results = resp.json().get("results") or []
        if not results:
            return {
                "ios_rating": None,
                "ios_ratings_count": None,
                "icon_url": None,
                "meta": {},
            }
        data = results[0]
        return {
            "ios_rating": data.get("averageUserRating"),
            "ios_ratings_count": data.get("userRatingCount"),
            "icon_url": data.get("artworkUrl100") or data.get("artworkUrl512"),
            "meta": {
                "trackName": data.get("trackName"),
                "sellerName": data.get("sellerName"),
                "bundleId": data.get("bundleId"),
                "version": data.get("version"),
                "primaryGenreName": data.get("primaryGenreName"),
                "trackViewUrl": data.get("trackViewUrl"),
                "currentVersionReleaseDate": data.get("currentVersionReleaseDate"),
                "description": (data.get("description") or "")[:500],
                "averageUserRatingForCurrentVersion": data.get(
                    "averageUserRatingForCurrentVersion"
                ),
                "userRatingCountForCurrentVersion": data.get(
                    "userRatingCountForCurrentVersion"
                ),
            },
        }


def fetch_ios_reviews(
    app_id: str,
    app_slug: str,
    *,
    country: str = "uz",
    pages: int = 5,
) -> list[dict[str, Any]]:
    """Fetch up to `pages` pages of most-recent reviews from Apple RSS.

    Apple RSS returns ~50 reviews per page, max 10 pages.
    Country code filters reviews shown for that storefront.
    """
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    countries = [country, "ru", "us"] if country != "us" else ["us"]

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for store_country in countries:
            for page in range(1, pages + 1):
                url = (
                    f"https://itunes.apple.com/{store_country}/rss/customerreviews/"
                    f"page={page}/id={app_id}/sortby=mostrecent/json"
                )
                try:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        break
                    payload = resp.json()
                except Exception:
                    break

                feed = payload.get("feed") or {}
                entries = feed.get("entry") or []
                if not entries:
                    break

                if isinstance(entries, dict):
                    entries = [entries]

                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    rating_node = entry.get("im:rating")
                    if not rating_node:
                        continue

                    review_id = _rss_label(entry.get("id"))
                    if not review_id or review_id in seen:
                        continue
                    seen.add(review_id)

                    author = _rss_label(((entry.get("author") or {}) if isinstance(entry.get("author"), dict) else {}).get("name"))
                    title = _rss_label(entry.get("title"))
                    body = _rss_label(entry.get("content"))
                    version = _rss_label(entry.get("im:version"))
                    rating_raw = _rss_label(rating_node)
                    updated = _rss_label(entry.get("updated"))

                    try:
                        rating = int(rating_raw) if rating_raw is not None else None
                    except (TypeError, ValueError):
                        rating = None

                    rows.append(
                        {
                            "id": f"ios:{review_id}",
                            "app_slug": app_slug,
                            "store": "ios",
                            "author": author,
                            "rating": rating,
                            "title": title,
                            "body": body,
                            "language": store_country,
                            "version": version,
                            "thumbs_up": 0,
                            "review_date": _iso_from_rss(updated),
                            "scraped_at": scraped_at,
                            "raw_json": json.dumps(entry, ensure_ascii=False, default=str),
                        }
                    )

    return rows
