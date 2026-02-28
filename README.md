# 📊 GooglePlayTop — Google Play Store Analytics Dashboard

A Flask-based dashboard that scrapes Google Play Store data to analyze top apps, discover niches, compare competitors, and track install growth over time.

> ⚠️ **Disclaimer:** This project is created strictly for **educational purposes**. The author takes no responsibility for any misuse or violations of Google's Terms of Service.

---
[![Buy Me a Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)]([https://ko-fi.com/ismailelbakkouchi])


## Features

- **Top 100 Apps** — Browse the most-downloaded apps across 36+ built-in categories
- **🎌 Anime Tab** — Top anime keywords and apps on Google Play
- **🔍 Competition Analyzer** — Scores keywords (0-100) based on demand, competition & opportunity to gauge how strong the competition is
- **Custom Categories** — Create your own categories with custom search queries and emoji, managed via the UI
- **Custom Niches** — Add custom keyword groups and analyze their competition
- **📊 App Comparison** — Select two apps, compare description keywords (word overlap), and view install growth charts
- **App Details Modal** — Click any app to see description, screenshots, downloads, ratings, release date
- **📊 Market Insights Panel** — Auto-generated stats for any category: avg rating, install distribution, developer concentration, genre breakdown, title keyword extraction
- **⚠️ Quality Gap Detection** — Identifies low-rated apps with high installs (opportunity signals)
- **💰 Revenue Estimates** — Rough revenue estimates for paid apps based on price × installs
- **🔗 App Clustering** — Groups apps by shared title keywords to reveal sub-niches
- **🔍 Filter Bar** — Search, filter by rating/installs/free-paid across any category view
- **⭐ Bookmarks & Notes** — Star any app, add research notes, view all bookmarks in the Analysis tab
- **📈 Growth Velocity** — Track fastest-growing apps from snapshot data (powered by scheduler)
- **📊 Category Comparison** — Side-by-side stats for any two categories (ratings, devs, keywords)
- **CSV Export** — Download any category's data as a spreadsheet
- **Snapshot & Diff** — Save snapshots over time, compare rankings to spot trends
- **Background Scheduler** — Auto-refresh all categories on a loop (hourly by default) with `scheduler.py`
- **Server-side Cancellation** — Switching tabs cancels the previous in-flight scrape instantly
- **IP Block Detection** — Modal warning with countdown when Google rate-limits you
- **Proxy Rotation** — Route requests through multiple proxies (configured via `.env`)
- **Human-like Scraping** — Rotating browser headers, random delays, shuffled queries, exponential backoff

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/iel-bakk/GooglePlayTop.git
cd GooglePlayTop
```

### 2. Install dependencies

```bash
pip install flask google-play-scraper python-dotenv
```

### 3. (Optional) Configure proxies

Create a `.env` file in the project root:

```env
# Comma-separated list of proxies (optional — works without them)
PROXIES=http://user:pass@host1:port,http://user:pass@host2:port

# Connection timeout in seconds
PROXY_TIMEOUT=10
```

If you skip this step, all requests go through your direct IP.

### 4. Run the server

```bash
python3 app.py
```

Open **http://localhost:5000** in your browser.

### 5. (Optional) Run the background scheduler

To auto-refresh all categories every hour without using the web UI:

```bash
python3 scheduler.py
```

The scheduler writes directly to the SQLite database. You can run it alongside `app.py` (data loads instantly from cache) or on its own.

---

## Project Structure

```
GooglePlayTop/
├── app.py             # Flask server — all API routes
├── scraper.py         # Google Play scraper with throttling & proxy support
├── database.py        # SQLite persistence layer (caching, snapshots, query log)
├── scheduler.py       # Background scheduler — auto-refreshes all categories
├── static/
│   └── index.html     # Single-page frontend (vanilla JS, CSS, Chart.js)
├── .env               # Proxy config (not tracked by git)
├── .gitignore
└── README.md
```

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/top` | GET | Top 100 most-downloaded apps |
| `/api/categories` | GET | List of available categories (built-in + custom) |
| `/api/category/<name>` | GET | Top 100 apps in a category |
| `/api/category/custom` | POST | Add a custom category |
| `/api/category/custom/<name>` | DELETE | Delete a custom category |
| `/api/anime/keywords` | GET | Top anime search keywords |
| `/api/anime/apps` | GET | Top anime apps |
| `/api/app/<package_id>` | GET | Full details for a single app |
| `/api/niches` | GET | List of available niches (built-in + custom) |
| `/api/niche/<name>/keywords` | GET | Keywords for a niche |
| `/api/niche/<name>/score` | GET | Competition score for a niche |
| `/api/niche/custom` | POST | Add a custom niche |
| `/api/niche/custom/<name>` | DELETE | Delete a custom niche |
| `/api/compare?app1=...&app2=...` | GET | Compare two apps' descriptions |
| `/api/install-history/<package_id>` | GET | Install count history from snapshots |
| `/api/notes/<app_id>` | GET | Get note/bookmark for an app |
| `/api/notes/<app_id>` | POST | Save note/bookmark for an app |
| `/api/notes/<app_id>` | DELETE | Delete note/bookmark |
| `/api/bookmarks` | GET | List all bookmarked apps |
| `/api/growth` | GET | Fastest-growing apps from snapshots |
| `/api/export/<category>` | GET | Download category data as CSV |
| `/api/snapshot/save` | POST | Save a snapshot of current data |
| `/api/snapshot/<key>` | GET | Retrieve a saved snapshot |
| `/api/snapshot/<key>/diff` | GET | Compare latest two snapshots |
| `/api/proxy-status` | GET | Current proxy pool health |
| `/api/throttle-status` | GET | Current throttle/cooldown state |
| `/api/cache-status` | GET | Cache freshness for all categories |
| `/api/eta` | GET | Estimated scraping duration |

---

## Anti-Ban Measures

The scraper includes several layers to avoid IP bans:

1. **Browser Headers** — Rotates through 8 real User-Agent strings (Chrome, Firefox, Safari, Edge) with full header fingerprints
2. **Human-like Timing** — Log-normal delay distribution (most requests 2-4s, occasional 7-12s "reading" pauses)
3. **Shuffled Queries** — Query order is randomized each run
4. **Session Cooldown** — 90-second minimum between batch scraping sessions
5. **Exponential Backoff** — Automatic increasing delays on consecutive errors
6. **SQLite Caching** — 6-hour TTL avoids redundant requests
7. **Proxy Rotation** — Optional multi-proxy pool with automatic dead-proxy detection
8. **Query Logging** — Tracks last query time to enforce cooldowns

---

## Tech Stack

- **Backend:** Python, Flask, google-play-scraper
- **Database:** SQLite (WAL mode)
- **Frontend:** Vanilla JS, CSS Grid, Chart.js
- **Proxy:** urllib with ProxyHandler, configured via `.env`

---

## License

MIT — use it for learning, research, and personal projects.
