"""SQLite persistence for app metadata and reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "reviews.db"
CATALOG_PATH = ROOT / "apps_catalog.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS apps (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                brand TEXT,
                play_id TEXT,
                ios_id TEXT,
                ios_bundle TEXT,
                play_rating REAL,
                play_ratings_count INTEGER,
                play_installs TEXT,
                ios_rating REAL,
                ios_ratings_count INTEGER,
                icon_url TEXT,
                last_synced_at TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                app_slug TEXT NOT NULL,
                store TEXT NOT NULL CHECK (store IN ('play', 'ios')),
                author TEXT,
                rating INTEGER,
                title TEXT,
                body TEXT,
                language TEXT,
                version TEXT,
                thumbs_up INTEGER DEFAULT 0,
                review_date TEXT,
                scraped_at TEXT NOT NULL,
                raw_json TEXT,
                FOREIGN KEY (app_slug) REFERENCES apps(slug)
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_app ON reviews(app_slug);
            CREATE INDEX IF NOT EXISTS idx_reviews_store ON reviews(store);
            CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date);
            CREATE INDEX IF NOT EXISTS idx_reviews_rating ON reviews(rating);

            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT,
                stats_json TEXT,
                error TEXT
            );
            """
        )


def load_catalog() -> dict[str, Any]:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def upsert_apps_from_catalog() -> int:
    catalog = load_catalog()
    count = 0
    with connect() as conn:
        for app in catalog["apps"]:
            conn.execute(
                """
                INSERT INTO apps (slug, name, brand, play_id, ios_id, ios_bundle)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name = excluded.name,
                    brand = excluded.brand,
                    play_id = excluded.play_id,
                    ios_id = excluded.ios_id,
                    ios_bundle = excluded.ios_bundle
                """,
                (
                    app["slug"],
                    app["name"],
                    app.get("brand"),
                    app.get("play_id"),
                    app.get("ios_id"),
                    app.get("ios_bundle"),
                ),
            )
            count += 1
    return count


def update_app_meta(slug: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [slug]
    with connect() as conn:
        conn.execute(f"UPDATE apps SET {cols} WHERE slug = ?", values)


def upsert_reviews(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    inserted = 0
    with connect() as conn:
        for r in rows:
            cur = conn.execute(
                """
                INSERT INTO reviews (
                    id, app_slug, store, author, rating, title, body,
                    language, version, thumbs_up, review_date, scraped_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    rating = excluded.rating,
                    title = excluded.title,
                    body = excluded.body,
                    thumbs_up = excluded.thumbs_up,
                    scraped_at = excluded.scraped_at,
                    raw_json = excluded.raw_json
                """,
                (
                    r["id"],
                    r["app_slug"],
                    r["store"],
                    r.get("author"),
                    r.get("rating"),
                    r.get("title"),
                    r.get("body"),
                    r.get("language"),
                    r.get("version"),
                    r.get("thumbs_up") or 0,
                    r.get("review_date"),
                    r.get("scraped_at") or utcnow(),
                    r.get("raw_json"),
                ),
            )
            inserted += cur.rowcount
    return inserted


def get_apps() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*,
                (SELECT COUNT(*) FROM reviews r WHERE r.app_slug = a.slug) AS review_count,
                (SELECT COUNT(*) FROM reviews r WHERE r.app_slug = a.slug AND r.store = 'play') AS play_review_count,
                (SELECT COUNT(*) FROM reviews r WHERE r.app_slug = a.slug AND r.store = 'ios') AS ios_review_count,
                (SELECT AVG(rating) FROM reviews r WHERE r.app_slug = a.slug) AS avg_review_rating
            FROM apps a
            ORDER BY a.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_app(slug: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM apps WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None


def query_reviews(
    *,
    app_slug: str | None = None,
    store: str | None = None,
    rating: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    params: list[Any] = []

    if app_slug:
        clauses.append("r.app_slug = ?")
        params.append(app_slug)
    if store:
        clauses.append("r.store = ?")
        params.append(store)
    if rating is not None:
        clauses.append("r.rating = ?")
        params.append(rating)
    if q:
        clauses.append("(r.body LIKE ? OR r.title LIKE ? OR r.author LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM reviews r {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT r.*, a.name AS app_name, a.brand
            FROM reviews r
            JOIN apps a ON a.slug = r.app_slug
            {where}
            ORDER BY COALESCE(r.review_date, r.scraped_at) DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], total


def dashboard_stats() -> dict[str, Any]:
    with connect() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_reviews,
                AVG(rating) AS avg_rating,
                SUM(CASE WHEN store = 'play' THEN 1 ELSE 0 END) AS play_count,
                SUM(CASE WHEN store = 'ios' THEN 1 ELSE 0 END) AS ios_count,
                SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative_count,
                SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS positive_count
            FROM reviews
            """
        ).fetchone()

        rating_dist = conn.execute(
            """
            SELECT rating, COUNT(*) AS count
            FROM reviews
            GROUP BY rating
            ORDER BY rating
            """
        ).fetchall()

        by_app = conn.execute(
            """
            SELECT a.slug, a.name, a.brand, a.play_rating, a.ios_rating,
                   a.play_ratings_count, a.ios_ratings_count,
                   COUNT(r.id) AS scraped_reviews,
                   AVG(r.rating) AS avg_scraped_rating,
                   SUM(CASE WHEN r.rating <= 2 THEN 1 ELSE 0 END) AS negatives
            FROM apps a
            LEFT JOIN reviews r ON r.app_slug = a.slug
            GROUP BY a.slug
            ORDER BY scraped_reviews DESC, a.name
            """
        ).fetchall()

        timeline = conn.execute(
            """
            SELECT substr(review_date, 1, 10) AS day,
                   COUNT(*) AS count,
                   AVG(rating) AS avg_rating
            FROM reviews
            WHERE review_date IS NOT NULL AND length(review_date) >= 10
            GROUP BY day
            ORDER BY day DESC
            LIMIT 90
            """
        ).fetchall()

        recent = conn.execute(
            """
            SELECT r.*, a.name AS app_name
            FROM reviews r
            JOIN apps a ON a.slug = r.app_slug
            ORDER BY COALESCE(r.review_date, r.scraped_at) DESC
            LIMIT 20
            """
        ).fetchall()

        keywords = conn.execute(
            """
            SELECT lower(body) AS body, rating
            FROM reviews
            WHERE body IS NOT NULL AND length(body) > 10
            ORDER BY review_date DESC
            LIMIT 2000
            """
        ).fetchall()

        last_sync = conn.execute(
            """
            SELECT * FROM sync_runs
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    return {
        "totals": dict(totals) if totals else {},
        "rating_distribution": [dict(r) for r in rating_dist],
        "by_app": [dict(r) for r in by_app],
        "timeline": list(reversed([dict(r) for r in timeline])),
        "recent_reviews": [dict(r) for r in recent],
        "keyword_sample": [dict(r) for r in keywords],
        "last_sync": dict(last_sync) if last_sync else None,
        "app_count": len(by_app),
    }


def start_sync_run() -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
            (utcnow(), "running"),
        )
        return int(cur.lastrowid)


def finish_sync_run(
    run_id: int,
    *,
    status: str,
    stats: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE sync_runs
            SET finished_at = ?, status = ?, stats_json = ?, error = ?
            WHERE id = ?
            """,
            (utcnow(), status, json.dumps(stats or {}), error, run_id),
        )
