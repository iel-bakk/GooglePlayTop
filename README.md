# GooglePlayTop — Google Play Store Analytics & Market Research Dashboard

**GooglePlayTop** is an open-source Python Flask dashboard for scraping, analyzing, and tracking Google Play Store data. Discover top-ranked Android apps, analyze keyword competition, compare competitors, and monitor install growth — all from a local web interface.

> ⚠️ **Disclaimer:** This project is created strictly for **educational purposes**. The author takes no responsibility for any misuse or violations of Google's Terms of Service.

---

[![Buy Me a Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/ismailelbakkouchi)

---

## What Is GooglePlayTop?

GooglePlayTop is a self-hosted Google Play Store scraper and analytics dashboard built with Python and Flask. It helps indie developers, ASO (App Store Optimization) researchers, and market analysts:

- Find the **top 100 apps** in any Google Play category
- Score **keyword competition** for niche research
- Track **install growth over time** using snapshots
- Compare two apps **side by side** with keyword overlap analysis
- Export data to **CSV** for further research

Whether you're doing **ASO research**, **competitor analysis**, or exploring **Android app market trends**, GooglePlayTop gives you structured data in a clean, interactive UI.

---

## Features

### 📊 App Discovery & Rankings
- **Top 100 Apps** — Browse the most-downloaded Android apps across 36+ built-in Google Play categories
- **🎌 Anime Tab** — Top anime-related keywords and apps on Google Play
- **Custom Categories** — Create your own categories with custom search queries and emoji, managed via the UI

### 🔍 Keyword & Niche Research
- **Competition Analyzer** — Scores keywords (0–100) based on demand, competition, and opportunity — ideal for ASO keyword research
- **Custom Niches** — Add custom keyword groups and analyze their competitive landscape
- **🔗 App Clustering** — Groups apps by shared title keywords to reveal sub-niches and market gaps

### 📈 Market Intelligence & Competitor Analysis
- **📊 App Comparison** — Select two apps, compare description keyword overlap, and view install growth charts
- **📊 Market Insights Panel** — Auto-generated stats: avg rating, install distribution, developer concentration, genre breakdown, and title keyword extraction
- **⚠️ Quality Gap Detection** — Identifies low-rated apps with high installs (opportunity signals for new developers)
- **💰 Revenue Estimates** — Rough revenue estimates for paid apps based on price × installs
- **📊 Category Comparison** — Side-by-side stats for any two categories

### 📅 Growth Tracking & Snapshots
- **📈 Growth Velocity** — Track fastest-growing Android apps from snapshot data (powered by scheduler)
- **Snapshot & Diff** — Save data snapshots over time, compare rankings to spot trends
- **Background Scheduler** — Auto-refresh all categories on a loop (hourly by default) with `scheduler.py`

### 🛠️ Usability & Data Management
- **App Details Modal** — Click any app to see description, screenshots, downloads, ratings, and release date
- **🔍 Filter Bar** — Search and filter by rating, installs, or free/paid status across any category
- **⭐ Bookmarks & Notes** — Star any app, add research notes, and view all bookmarks in the Analysis tab
- **CSV Export** — Download any category's data as a spreadsheet for offline analysis
- **Server-side Cancellation** — Switching tabs cancels the previous in-flight scrape instantly

### 🛡️ Anti-Ban & Proxy Support
- **IP Block Detection** — Modal warning with countdown when Google rate-limits your IP
- **Proxy Rotation** — Route requests through multiple proxies (configured via `.env`)
- **Human-like Scraping** — Rotating browser headers, random delays, shuffled queries, exponential backoff

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/iel-bakk/GooglePlayTop.git
cd GooglePlayTop
```

### 2. Install Python Dependencies

```bash
pip install flask google-play-scraper python-dotenv
```

### 3. (Optional) Configure Proxies

Create a `.env` file in the project root to avoid IP bans during large scraping sessions:

```env
# Comma-separated list of proxies (optional — works without them)
PROXIES=http://user:pass@host1:port,http://user:pass@host2:port

# Connection timeout in seconds
PROXY_TIMEOUT=10
```

If you skip this step, all requests go through your direct IP.

### 4. Run the Flask Server

```bash
python3 app.py
```

Open **http://localhost:5000** in your browser.

### 5. (Optional) Run the Background Scheduler

To auto-refresh all Google Play categories every hour without using the web UI:

```bash
python3 scheduler.py
```

The scheduler writes directly to the SQLite database. Run it alongside `app.py` for instant cache loads, or on its own as a standalone data collector.

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

## API Reference

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

The scraper includes several layers to avoid Google Play IP bans:

1. **Browser Headers** — Rotates through 8 real User-Agent strings (Chrome, Firefox, Safari, Edge) with full header fingerprints
2. **Human-like Timing** — Log-normal delay distribution (most requests 2–4s, occasional 7–12s "reading" pauses)
3. **Shuffled Queries** — Query order is randomized each run
4. **Session Cooldown** — 90-second minimum between batch scraping sessions
5. **Exponential Backoff** — Automatic increasing delays on consecutive errors
6. **SQLite Caching** — 6-hour TTL avoids redundant requests
7. **Proxy Rotation** — Optional multi-proxy pool with automatic dead-proxy detection
8. **Query Logging** — Tracks last query time to enforce cooldowns

---

## Use Cases

- **ASO (App Store Optimization)** — Find low-competition keywords with high install volume
- **Android App Market Research** — Understand category trends, top developers, and genre distribution
- **Competitor Benchmarking** — Compare your app's keyword overlap and install trajectory against rivals
- **Niche Discovery** — Use clustering and gap detection to find underserved categories on Google Play
- **Growth Tracking** — Monitor which apps are rising fastest in any category over time

---

## Tech Stack

- **Backend:** Python 3, Flask, google-play-scraper
- **Database:** SQLite (WAL mode)
- **Frontend:** Vanilla JavaScript, CSS Grid, Chart.js
- **Proxy Support:** urllib with ProxyHandler, configured via `.env`

---

## License

MIT — free to use for learning, research, and personal projects.

---
