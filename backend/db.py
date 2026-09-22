"""SQLite persistence for app metadata and reviews."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "reviews.db"
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
                store TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS telegram_posts (
                review_id TEXT PRIMARY KEY,
                rating INTEGER,
                posted_at TEXT NOT NULL,
                FOREIGN KEY (review_id) REFERENCES reviews(id)
            );

            CREATE TABLE IF NOT EXISTS telegram_summaries (
                day TEXT PRIMARY KEY,
                posted_at TEXT NOT NULL,
                payload_json TEXT
            );
            """
        )
        _migrate_reviews_store(conn)
        for col, decl in (
            ("huawei_id", "TEXT"),
            ("huawei_rating", "REAL"),
            ("xiaomi_id", "TEXT"),
            ("xiaomi_rating", "REAL"),
        ):
            _ensure_column(conn, "apps", col, decl)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_reviews_store(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='reviews'"
    ).fetchone()
    sql = (row[0] if row else "") or ""
    if "play', 'ios'" not in sql and "play', 'ios" not in sql:
        # already migrated or created without CHECK
        if "CHECK" not in sql:
            return
    if "huawei" in sql:
        return
    # telegram_posts.review_id references reviews(id); rebuilding the table
    # (drop + rename) with FK enforcement on would fail once that table has rows.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reviews_v2 (
                id TEXT PRIMARY KEY,
                app_slug TEXT NOT NULL,
                store TEXT NOT NULL,
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
            INSERT OR IGNORE INTO reviews_v2
            SELECT id, app_slug, store, author, rating, title, body, language, version,
                   thumbs_up, review_date, scraped_at, raw_json FROM reviews;
            DROP TABLE reviews;
            ALTER TABLE reviews_v2 RENAME TO reviews;
            CREATE INDEX IF NOT EXISTS idx_reviews_app ON reviews(app_slug);
            CREATE INDEX IF NOT EXISTS idx_reviews_store ON reviews(store);
            CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date);
            CREATE INDEX IF NOT EXISTS idx_reviews_rating ON reviews(rating);
            """
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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
                INSERT INTO apps (slug, name, brand, play_id, ios_id, ios_bundle, huawei_id, xiaomi_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name = excluded.name,
                    brand = excluded.brand,
                    play_id = excluded.play_id,
                    ios_id = excluded.ios_id,
                    ios_bundle = excluded.ios_bundle,
                    huawei_id = COALESCE(excluded.huawei_id, apps.huawei_id),
                    xiaomi_id = COALESCE(excluded.xiaomi_id, apps.xiaomi_id)
                """,
                (
                    app["slug"],
                    app["name"],
                    app.get("brand"),
                    app.get("play_id"),
                    app.get("ios_id"),
                    app.get("ios_bundle"),
                    app.get("huawei_id"),
                    app.get("xiaomi_id") or app.get("play_id"),
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
                SUM(CASE WHEN store = 'huawei' THEN 1 ELSE 0 END) AS huawei_count,
                SUM(CASE WHEN store = 'xiaomi' THEN 1 ELSE 0 END) AS xiaomi_count,
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


def unposted_star_reviews(
    *,
    ratings: tuple[int, ...] = (1, 2, 3, 4, 5),
    since_iso: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(ratings))
    clauses = [
        f"r.rating IN ({placeholders})",
        "r.body IS NOT NULL",
        "length(trim(r.body)) >= 20",
        "t.review_id IS NULL",
    ]
    params: list[Any] = list(ratings)
    if since_iso:
        clauses.append("COALESCE(r.review_date, r.scraped_at) >= ?")
        params.append(since_iso)
    where = " AND ".join(clauses)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, a.name AS app_name, a.brand
            FROM reviews r
            JOIN apps a ON a.slug = r.app_slug
            LEFT JOIN telegram_posts t ON t.review_id = r.id
            WHERE {where}
            ORDER BY COALESCE(r.review_date, r.scraped_at) DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        return [dict(row) for row in rows]


def reviews_in_range(
    *,
    start_iso: str,
    end_iso: str,
    slugs: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    clauses = ["COALESCE(r.review_date, r.scraped_at) >= ?", "COALESCE(r.review_date, r.scraped_at) < ?"]
    params: list[Any] = [start_iso, end_iso]
    if slugs:
        placeholders = ",".join("?" * len(slugs))
        clauses.append(f"r.app_slug IN ({placeholders})")
        params.extend(slugs)
    where = " AND ".join(clauses)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, a.name AS app_name, a.brand
            FROM reviews r
            JOIN apps a ON a.slug = r.app_slug
            WHERE {where}
            ORDER BY COALESCE(r.review_date, r.scraped_at) DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def summary_posted(day: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM telegram_summaries WHERE day = ?", (day,)
        ).fetchone()
        return bool(row)


def mark_summary_posted(day: str, payload: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO telegram_summaries (day, posted_at, payload_json)
            VALUES (?, ?, ?)
            """,
            (day, utcnow(), json.dumps(payload or {}, ensure_ascii=False)),
        )


def mark_telegram_posted(review_id: str, rating: int | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO telegram_posts (review_id, rating, posted_at)
            VALUES (?, ?, ?)
            """,
            (review_id, rating, utcnow()),
        )


def last_successful_sync() -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM sync_runs
            WHERE status = 'ok'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


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
