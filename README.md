# 📊 GooglePlayTop — Google Play Store Analytics Dashboard

A Flask-based dashboard that scrapes Google Play Store data to analyze top apps, discover niches, compare competitors, and track install growth over time.

> ⚠️ **Disclaimer:** This project is created strictly for **educational purposes**. The author takes no responsibility for any misuse or violations of Google's Terms of Service.

---

## Features

- **Top 100 Apps** — Browse the most-downloaded apps across 15+ categories
- **🎌 Anime Tab** — Top anime keywords and apps on Google Play
- **🔍 Niche Finder** — Scores niches (0-100) based on demand, competition & opportunity
- **📊 App Comparison** — Select two apps, compare description keywords (word overlap), and view install growth charts
- **App Details Modal** — Click any app to see description, screenshots, downloads, ratings, release date
- **CSV Export** — Download any category's data as a spreadsheet
- **Snapshot & Diff** — Save snapshots over time, compare rankings to spot trends
- **IP Block Detection** — Modal warning with countdown when Google rate-limits you
- **Proxy Rotation** — Route requests through multiple proxies (configured via `.env`)
- **Human-like Scraping** — Rotating browser headers, log-normal delays, shuffled queries, exponential backoff

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

---

## Project Structure

```
GooglePlayTop/
├── app.py             # Flask server — all API routes
├── scraper.py         # Google Play scraper with throttling & proxy support
├── database.py        # SQLite persistence layer (caching, snapshots, query log)
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
| `/api/categories` | GET | List of available categories |
| `/api/category/<name>` | GET | Top 100 apps in a category |
| `/api/anime/keywords` | GET | Top anime search keywords |
| `/api/anime/apps` | GET | Top anime apps |
| `/api/app/<package_id>` | GET | Full details for a single app |
| `/api/niches` | GET | List of available niches |
| `/api/niche/<name>/keywords` | GET | Keywords for a niche |
| `/api/niche/<name>/score` | GET | Opportunity score for a niche |
| `/api/niche/scores` | GET | All niche scores ranked |
| `/api/compare?app1=...&app2=...` | GET | Compare two apps' descriptions |
| `/api/install-history/<package_id>` | GET | Install count history from snapshots |
| `/api/export/<category>` | GET | Download category data as CSV |
| `/api/snapshot/save` | POST | Save a snapshot of current data |
| `/api/snapshot/<key>` | GET | Retrieve a saved snapshot |
| `/api/snapshot/<key>/diff` | GET | Compare latest two snapshots |
| `/api/proxy-status` | GET | Current proxy pool health |

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
