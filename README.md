# UZ Finance Reviews Dashboard

Review intelligence dashboard for **Uzbekistan finance apps** on **Google Play** and the **Apple App Store**.

Track ratings, scrape recent reviews, compare competitors, and surface common themes (payments, crashes, support, cashback, etc.).

## Features

- Curated catalog of major UZ finance / banking / wallet apps
- Play Store metadata + newest reviews (`google-play-scraper`)
- App Store metadata (iTunes Lookup) + reviews (Apple RSS)
- Local SQLite storage (`data/reviews.db`)
- Dashboard: KPIs, leaderboard, rating distribution, timeline, themes, keyword chips
- Filterable review browser (app / store / star / text search)
- One-click re-sync from the UI (disabled on public share by default)

## Quick start (local)

```bash
cd ~/uz-finance-reviews
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Seed data (scrapes all catalog apps — a few minutes)
python scripts/sync.py

# Run dashboard
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**

---

## Permanent host (recommended for colleagues)

Hosts on **[Fly.io](https://fly.io)** with a stable HTTPS URL. Your Mac can sleep — the cloud app stays online.

### One-time setup

1. Install is already done if you ran earlier steps (`~/.fly/bin/flyctl`).
2. Open **Terminal** and run:

```bash
cd ~/uz-finance-reviews
./scripts/deploy-fly.sh
```

Or double-click:

`scripts/open-deploy-terminal.command`

3. A browser opens for **Fly.io login** (card required).
4. Live URL:

**https://uz-finance-reviews.fly.dev**

**Defaults on Fly**
- No password (open for colleagues)
- Sync button locked (`DASHBOARD_READONLY=1`)
- Seeded with your current `data/reviews.db`
- Free-tier machine sleeps when idle; first open after idle may take ~5–10s to wake

### Re-deploy (after code or data changes)

```bash
# optional: refresh store data first
source .venv/bin/activate && python scripts/sync.py

./scripts/deploy-fly.sh
```

### Alternative: Render

1. Push this folder to GitHub (include `data/reviews.db` if you want seed data).
2. [Render](https://render.com) → New → Blueprint → select repo (`render.yaml` is included).
3. Free web service URL like `https://uz-finance-reviews.onrender.com` (cold starts on free plan).

---

## Temporary share (Mac must stay awake)

```bash
./scripts/share.sh
```

Prints a `https://….trycloudflare.com` link. Changes every restart; good for quick demos only.

### Same Wi‑Fi only

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Share `http://<your-lan-ip>:8000`.

---

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Liveness + auth/readonly flags |
| `GET /api/dashboard` | Aggregates, charts, themes |
| `GET /api/apps` | Catalog + store ratings |
| `GET /api/reviews` | Paginated reviews (`app`, `store`, `rating`, `q`) |
| `POST /api/sync` | Background resync (blocked when readonly) |

## Catalog

Edit `apps_catalog.json` to add/remove apps:

- `slug`, `name`, `brand`
- `play_id` (package name) and/or `ios_id` (numeric App Store ID)

## Notes

- Scraping uses public store endpoints; be respectful with frequency.
- Apple RSS is limited (~50 reviews × up to 10 pages per storefront).
- Play scraper fetches newest reviews for `country=uz` (ru + uz language).
- Optional password: set `DASHBOARD_PASSWORD` in `.env` or Fly secrets.
