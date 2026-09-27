"""Google Play Developer API: device details for reviews of apps we manage."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

SCOPE = "https://www.googleapis.com/auth/androidpublisher"
REVIEWS_URL = (
    "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package}/reviews"
)

# The API reports the Android API level; people know the release number
ANDROID_RELEASES = {
    21: "5.0", 22: "5.1", 23: "6", 24: "7.0", 25: "7.1", 26: "8.0", 27: "8.1",
    28: "9", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13", 34: "14",
    35: "15", 36: "16",
}
PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")


def enabled() -> bool:
    return bool(os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip())


def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    info = json.loads(os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    return AuthorizedSession(creds)


def _device_name(meta: dict[str, Any], fallback: str | None) -> str | None:
    # productName looks like "rubypro (Redmi Note 12 Pro+ 5G)"; the part in brackets is the model
    product = (meta.get("productName") or "").strip()
    m = PAREN_RE.search(product)
    model = m.group(1).strip() if m else product or (fallback or "").strip()
    maker = (meta.get("manufacturer") or "").strip()
    if maker and model and not model.lower().startswith(maker.lower()):
        model = f"{maker} {model}"
    return model or None


def _row(review: dict[str, Any], app_slug: str) -> dict[str, Any] | None:
    comment = next(
        (c["userComment"] for c in review.get("comments") or [] if c.get("userComment")), None
    )
    if not comment or not review.get("reviewId"):
        return None
    meta = comment.get("deviceMetadata") or {}
    api_level = comment.get("androidOsVersion")
    seconds = (comment.get("lastModified") or {}).get("seconds")
    device_class = (meta.get("deviceClass") or "").removeprefix("FORM_FACTOR_").lower()
    return {
        "id": f"play:{review['reviewId']}",
        "app_slug": app_slug,
        "store": "play",
        "author": review.get("authorName"),
        "rating": comment.get("starRating"),
        "title": None,
        "body": (comment.get("text") or "").strip(),
        "language": comment.get("reviewerLanguage"),
        "version": comment.get("appVersionName"),
        "thumbs_up": comment.get("thumbsUpCount") or 0,
        # Only used for reviews the public listing doesn't show; existing rows keep their date
        "review_date": datetime.fromtimestamp(int(seconds), tz=timezone.utc).isoformat()
        if seconds
        else None,
        "raw_json": json.dumps(review, ensure_ascii=False),
        "device": _device_name(meta, comment.get("device")),
        "device_class": device_class or None,
        "os_version": f"Android {ANDROID_RELEASES.get(api_level, api_level)}" if api_level else None,
    }


def fetch_reviews(package: str, app_slug: str) -> list[dict[str, Any]]:
    """Reviews with text created or edited in the last 7 days (the API's window)."""
    session = _session()
    rows: list[dict[str, Any]] = []
    token = None
    for _ in range(20):
        params: dict[str, Any] = {"maxResults": 100}
        if token:
            params["token"] = token
        resp = session.get(REVIEWS_URL.format(package=package), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows += [r for r in (_row(rv, app_slug) for rv in data.get("reviews") or []) if r]
        token = (data.get("tokenPagination") or {}).get("nextPageToken")
        if not token:
            break
    return rows
