"""Post 1–5★ reviews with real context to a Telegram channel."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend import db

GENERIC_PHRASES = {
    "zor",
    "zur",
    "zo'r",
    "zo‘r",
    "zo`r",
    "super",
    "good",
    "bad",
    "nice",
    "ok",
    "okay",
    "cool",
    "best",
    "worst",
    "love",
    "hate",
    "perfect",
    "yaxshi",
    "yomon",
    "alo",
    "a'lo",
    "juda yaxshi",
    "juda yomon",
    "judayam yaxshi",
    "judayam yomon",
    "not good",
    "not bad",
    "very good",
    "very bad",
    "so good",
    "so bad",
    "too bad",
    "the best",
    "the worst",
    "хорошо",
    "плохо",
    "отлично",
    "супер",
    "норм",
    "нормально",
    "ужас",
    "класс",
    "круто",
    "огонь",
    "топ",
    "ваще топ",
    "не работает",
    "работает",
    "okey",
    "ок",
    "окей",
    "👍",
    "👎",
    "🔥",
    "❤️",
    "❤",
    "😍",
    "😡",
}

GENERIC_TOKENS = {
    "zor",
    "zur",
    "super",
    "good",
    "bad",
    "nice",
    "ok",
    "okay",
    "cool",
    "app",
    "best",
    "worst",
    "love",
    "hate",
    "yaxshi",
    "yomon",
    "juda",
    "judayam",
    "alo",
    "very",
    "so",
    "too",
    "not",
    "the",
    "this",
    "that",
    "and",
    "but",
    "хорошо",
    "плохо",
    "отлично",
    "супер",
    "норм",
    "нормально",
    "ужас",
    "класс",
    "круто",
    "приложение",
    "ilova",
    "ilovani",
    "ok",
    "ок",
}

WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁўқғҳʼ'’-]{2,}", re.UNICODE)
EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002700-\U000027bf"
    "\U0001f600-\U0001f64f"
    "]+",
    flags=re.UNICODE,
)


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("‘", "'").replace("’", "'").replace("`", "'")
    t = EMOJI_RE.sub(" ", t)
    t = re.sub(r"[^\w\s'’-]+", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def has_context(review: dict[str, Any], *, min_chars: int = 20, min_words: int = 3) -> bool:
    """Keep 1–5★ reviews that explain something; drop 'zor' / 'good' / 'not good'."""
    rating = review.get("rating")
    if rating not in (1, 2, 3, 4, 5):
        return False

    raw = " ".join(
        p for p in ((review.get("title") or ""), (review.get("body") or "")) if p
    ).strip()
    if not raw:
        return False

    letters_only = re.sub(r"\s+", "", EMOJI_RE.sub("", raw))
    if len(letters_only) < min_chars:
        return False

    norm = _norm(raw)
    if not norm or norm in GENERIC_PHRASES:
        return False

    words = WORD_RE.findall(norm)
    if len(words) < min_words:
        return False

    content = [w for w in words if w not in GENERIC_TOKENS and len(w) > 2]
    if len(content) < 2:
        return False
    return True


def enabled() -> bool:
    return bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )


def _lookback_hours() -> float:
    try:
        return max(float(os.getenv("TELEGRAM_LOOKBACK_HOURS", "48")), 1.0)
    except ValueError:
        return 48.0


STAR_TAGS = {
    5: "5★ praise",
    4: "4★ mostly positive",
    3: "3★ mixed",
    2: "2★ negative",
    1: "1★ complaint",
}

APP_HASHTAGS = {"alif-mobi": "#Alif"}

SUMMARY_APP_SLUGS = ("alif-mobi", "click", "payme", "paynet", "xazna", "uzum-bank")
TASHKENT = timezone(timedelta(hours=5))
# Store feeds publish reviews ~a day late (keeping the original timestamp), so
# summarising yesterday right after midnight misses most of its reviews.
SUMMARY_DAYS_BACK = 2


def format_message(review: dict[str, Any]) -> str:
    rating = int(review.get("rating") or 0)
    stars = "⭐" * max(1, min(rating, 5))
    tag = STAR_TAGS.get(rating, f"{rating}★")
    store = {
        "play": "Play Store",
        "ios": "App Store",
        "huawei": "AppGallery",
        "xiaomi": "GetApps",
    }.get(review.get("store") or "", review.get("store") or "Store")
    app = review.get("app_name") or review.get("app_slug") or "App"
    author = review.get("author") or "Anonymous"
    date = (review.get("review_date") or review.get("scraped_at") or "")[:10]
    version = review.get("version")
    title = (review.get("title") or "").strip()
    body = (review.get("body") or "").strip()
    text = f"{title}\n{body}".strip() if title and title not in body else body
    if len(text) > 1200:
        text = text[:1190] + "…"

    lines = [
        f"<b>{_esc(app)}</b>  {stars} · {tag}",
        f"{store} · {_esc(author)} · {date}"
        + (f" · v{_esc(version)}" if version else ""),
        "",
        _esc(text),
    ]
    hashtag = APP_HASHTAGS.get(review.get("app_slug") or "")
    if hashtag:
        lines += ["", hashtag]
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _redact(text: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return text.replace(token, "***")
    return text


def send_message(text: str, *, retries: int = 4) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram is not configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    last_exc: Exception | None = None
    with httpx.Client(timeout=30.0) as client:
        for attempt in range(retries):
            try:
                resp = client.post(url, json=payload)
                if resp.status_code == 429:
                    wait = 3 * (attempt + 1)
                    retry_after = None
                    try:
                        retry_after = (resp.json().get("parameters") or {}).get(
                            "retry_after"
                        )
                    except Exception:
                        retry_after = None
                    time.sleep(int(retry_after or wait))
                    last_exc = RuntimeError("Telegram rate-limited")
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description") or "Telegram send failed")
                return
            except Exception as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(_redact(str(last_exc or "Telegram send failed")))


def preview_candidates(limit: int = 20) -> list[dict[str, Any]]:
    since = (
        datetime.now(timezone.utc) - timedelta(hours=_lookback_hours())
    ).isoformat()
    rows = db.unposted_star_reviews(since_iso=since, limit=200)
    out = []
    for r in rows:
        if has_context(r):
            out.append(r)
        if len(out) >= limit:
            break
    return out


THEME_LABELS = {
    "payments": "payments / transfers",
    "cards": "cards",
    "cashback": "cashback",
    "support": "support",
    "login_auth": "login / SMS / PIN",
    "crashes": "crashes / app not working",
    "updates": "updates",
    "loans_credit": "loans / nasiya",
    "fees": "fees / commissions",
    "ui_ux": "UI / UX",
}


def tashkent_day_range(days_back: int = SUMMARY_DAYS_BACK) -> tuple[str, str, str]:
    now = datetime.now(TASHKENT)
    day = now.date() - timedelta(days=days_back)
    start = datetime(day.year, day.month, day.day, tzinfo=TASHKENT).astimezone(
        timezone.utc
    )
    end = start + timedelta(days=1)
    return day.isoformat(), start.isoformat(), end.isoformat()


def _complaint_sentence(reviews: list[dict[str, Any]]) -> str:
    from backend.analytics import extract_themes

    neg_texts = [
        (r.get("body") or "")
        for r in reviews
        if (r.get("rating") or 5) <= 2 and (r.get("body") or "").strip()
    ]
    if not neg_texts:
        return "No notable complaints."
    themes = extract_themes(neg_texts)
    if not themes:
        return "Complaints were mixed."
    labels = [THEME_LABELS.get(t["theme"], t["theme"]) for t in themes[:3]]
    return "Complaints: " + ", ".join(labels) + "."


def format_daily_summary(day: str, by_slug: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        f"📊 <b>Daily recap</b> · {day} (Tashkent)",
        "Alif · Click · Payme · Paynet · Xazna · Uzum",
        "",
    ]
    names = {
        "alif-mobi": "Alif Mobi",
        "click": "Click",
        "payme": "Payme",
        "paynet": "Paynet",
        "xazna": "Xazna",
        "uzum-bank": "Uzum Bank",
    }
    for slug in SUMMARY_APP_SLUGS:
        rows = by_slug.get(slug) or []
        name = names.get(slug, slug)
        counts = {n: 0 for n in range(1, 6)}
        for r in rows:
            try:
                star = int(r.get("rating") or 0)
            except (TypeError, ValueError):
                continue
            if 1 <= star <= 5:
                counts[star] += 1
        total = sum(counts.values())
        dist = " · ".join(f"{n}★ {counts[n]}" for n in range(1, 6))
        lines.append(f"<b>{_esc(name)}</b> — {total} reviews")
        lines.append(dist)
        lines.append(_esc(_complaint_sentence(rows)))
        lines.append("")
    return "\n".join(lines).strip()


def maybe_post_daily_summary(*, dry_run: bool = False) -> dict[str, Any]:
    day, start_iso, end_iso = tashkent_day_range()
    out: dict[str, Any] = {"day": day, "posted": False, "skipped": False}
    if db.summary_posted(day):
        out["skipped"] = True
        return out
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for slug in SUMMARY_APP_SLUGS:
        by_slug[slug] = db.reviews_in_range(
            start_iso=start_iso, end_iso=end_iso, slugs=[slug]
        )
    text = format_daily_summary(day, by_slug)
    out["preview"] = text
    if dry_run or not enabled():
        return out
    send_message(text)
    db.mark_summary_posted(day, {"counts": {s: len(v) for s, v in by_slug.items()}})
    out["posted"] = True
    return out


def notify_new_reviews(*, dry_run: bool = False) -> dict[str, Any]:
    """Send new 1–5★ contextual reviews, then yesterday's competitor summary."""
    stats = {
        "enabled": enabled(),
        "considered": 0,
        "skipped_short": 0,
        "posted": 0,
        "failed": 0,
        "deferred": 0,
        "errors": [],
    }
    if not enabled() and not dry_run:
        return stats

    since = (
        datetime.now(timezone.utc) - timedelta(hours=_lookback_hours())
    ).isoformat()
    rows = db.unposted_star_reviews(since_iso=since, limit=400)
    stats["considered"] = len(rows)

    # Post oldest first so the channel reads chronologically
    rows = list(reversed(rows))
    max_per_run = int(os.getenv("TELEGRAM_MAX_PER_RUN", "30"))
    for review in rows:
        if not has_context(review):
            stats["skipped_short"] += 1
            continue
        if dry_run:
            stats["posted"] += 1
            continue
        if stats["posted"] >= max_per_run:
            stats["deferred"] = stats.get("deferred", 0) + 1
            continue
        try:
            send_message(format_message(review))
            db.mark_telegram_posted(review["id"], review.get("rating"))
            stats["posted"] += 1
            time.sleep(3.1)  # Telegram allows ~20 msgs/min to one chat
        except Exception as exc:
            stats["errors"].append(f"{review.get('id')}: {_redact(str(exc))}")
            stats["failed"] += 1
            if stats["failed"] >= 3:
                break
    try:
        stats["summary"] = maybe_post_daily_summary(dry_run=dry_run)
    except Exception as exc:
        stats["summary"] = {"posted": False, "error": _redact(str(exc))}
    return stats
