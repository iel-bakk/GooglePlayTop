"""
SQLite persistence layer for scraped Google Play data.

Stores app results and anime keywords with timestamps so we can
serve data from the DB when it's still fresh and avoid hitting
Google Play too often (which causes IP bans).
"""

import sqlite3
import json
import os
import time
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "playstore.db")

# How long cached data stays valid before we re-scrape (in hours)
CACHE_TTL_HOURS = 6


def _connect():
    """Return a connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key   TEXT    NOT NULL,
            app_data    TEXT    NOT NULL,   -- JSON blob
            fetched_at  TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_cache_key ON app_cache(cache_key);

        CREATE TABLE IF NOT EXISTS keyword_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key   TEXT    NOT NULL,
            kw_data     TEXT    NOT NULL,   -- JSON blob
            fetched_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kw_key ON keyword_cache(cache_key);

        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            snap_key    TEXT    NOT NULL,   -- e.g. "general_top" or "cat_Games"
            snap_data   TEXT    NOT NULL,   -- JSON blob
            taken_at    TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_snap_key ON snapshots(snap_key);

        CREATE TABLE IF NOT EXISTS query_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query_type  TEXT    NOT NULL,   -- e.g. 'search', 'detail', 'batch'
            query_info  TEXT    NOT NULL,   -- what was queried
            queried_at  TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_query_log_time ON query_log(queried_at);

        CREATE TABLE IF NOT EXISTS request_timing (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint    TEXT    NOT NULL,   -- e.g. 'top', 'category:Games', 'anime'
            duration    REAL    NOT NULL,   -- seconds the request took
            cached      INTEGER NOT NULL DEFAULT 0,  -- 1 if served from cache
            recorded_at TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_timing_ep ON request_timing(endpoint);

        CREATE TABLE IF NOT EXISTS custom_niches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            niche_name  TEXT    NOT NULL UNIQUE,
            keywords    TEXT    NOT NULL,   -- JSON array of keyword strings
            created_at  TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_custom_niche_name ON custom_niches(niche_name);

        CREATE TABLE IF NOT EXISTS custom_categories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT    NOT NULL UNIQUE,
            queries       TEXT    NOT NULL,   -- JSON array of search query strings
            emoji         TEXT    NOT NULL DEFAULT '📂',
            created_at    TEXT    NOT NULL    -- ISO timestamp
        );
        CREATE INDEX IF NOT EXISTS idx_custom_cat_name ON custom_categories(category_name);

        CREATE TABLE IF NOT EXISTS app_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id      TEXT    NOT NULL UNIQUE,
            note_text   TEXT    NOT NULL DEFAULT '',
            bookmarked  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_app_notes_id ON app_notes(app_id);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# App cache helpers
# ---------------------------------------------------------------------------

def get_cached_apps(cache_key):
    """Return cached app list if still fresh, else None."""
    conn = _connect()
    row = conn.execute(
        "SELECT app_data, fetched_at FROM app_cache WHERE cache_key = ? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (cache_key,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    fetched_at = datetime.fromisoformat(row["fetched_at"])
    if datetime.utcnow() - fetched_at > timedelta(hours=CACHE_TTL_HOURS):
        return None  # stale

    return json.loads(row["app_data"])


def save_apps(cache_key, apps_list):
    """Persist a list of serialised app dicts under `cache_key`."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    # Remove old entries for this key to keep the table tidy
    conn.execute("DELETE FROM app_cache WHERE cache_key = ?", (cache_key,))
    conn.execute(
        "INSERT INTO app_cache (cache_key, app_data, fetched_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(apps_list), now),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Keyword cache helpers
# ---------------------------------------------------------------------------

def get_cached_keywords(cache_key):
    """Return cached keyword list if still fresh, else None."""
    conn = _connect()
    row = conn.execute(
        "SELECT kw_data, fetched_at FROM keyword_cache WHERE cache_key = ? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (cache_key,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    fetched_at = datetime.fromisoformat(row["fetched_at"])
    if datetime.utcnow() - fetched_at > timedelta(hours=CACHE_TTL_HOURS):
        return None

    return json.loads(row["kw_data"])


def save_keywords(cache_key, kw_list):
    """Persist a list of keyword dicts under `cache_key`."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute("DELETE FROM keyword_cache WHERE cache_key = ?", (cache_key,))
    conn.execute(
        "INSERT INTO keyword_cache (cache_key, kw_data, fetched_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(kw_list), now),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Snapshot helpers – for tracking changes over time
# ---------------------------------------------------------------------------

def save_snapshot(snap_key, data):
    """Save a point-in-time snapshot (keeps all history)."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO snapshots (snap_key, snap_data, taken_at) VALUES (?, ?, ?)",
        (snap_key, json.dumps(data), now),
    )
    conn.commit()
    conn.close()


def get_snapshots(snap_key, limit=10):
    """Return the last `limit` snapshots for a key, newest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT snap_data, taken_at FROM snapshots WHERE snap_key = ? "
        "ORDER BY taken_at DESC LIMIT ?",
        (snap_key, limit),
    ).fetchall()
    conn.close()
    return [{"data": json.loads(r["snap_data"]), "takenAt": r["taken_at"]} for r in rows]


def get_latest_two_snapshots(snap_key):
    """Return the two most recent snapshots for diff comparison."""
    conn = _connect()
    rows = conn.execute(
        "SELECT snap_data, taken_at FROM snapshots WHERE snap_key = ? "
        "ORDER BY taken_at DESC LIMIT 2",
        (snap_key,),
    ).fetchall()
    conn.close()
    return [{"data": json.loads(r["snap_data"]), "takenAt": r["taken_at"]} for r in rows]


# ---------------------------------------------------------------------------
# Query log – tracks when we last hit Google Play
# ---------------------------------------------------------------------------

def log_query(query_type, query_info):
    """Record that a query was made right now."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO query_log (query_type, query_info, queried_at) VALUES (?, ?, ?)",
        (query_type, query_info, now),
    )
    conn.commit()
    conn.close()


def get_last_query_time():
    """Return the datetime of the most recent query, or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT queried_at FROM query_log ORDER BY queried_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return datetime.fromisoformat(row["queried_at"])


def seconds_since_last_query():
    """Return seconds elapsed since the last Google Play query, or None."""
    last = get_last_query_time()
    if last is None:
        return None
    return (datetime.utcnow() - last).total_seconds()


# ---------------------------------------------------------------------------
# Request timing – track how long each endpoint takes
# ---------------------------------------------------------------------------

def log_request_timing(endpoint, duration, cached=False):
    """Record how long an endpoint request took."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO request_timing (endpoint, duration, cached, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (endpoint, round(duration, 2), 1 if cached else 0, now),
    )
    conn.commit()
    conn.close()


def get_avg_duration(endpoint):
    """Return average duration (seconds) for an endpoint from the last 10
    non-cached requests.  Falls back to cached requests if no non-cached
    data exists. Returns None if no data at all."""
    conn = _connect()
    # Prefer non-cached timings
    row = conn.execute(
        "SELECT AVG(duration) as avg_dur, COUNT(*) as cnt "
        "FROM (SELECT duration FROM request_timing "
        "      WHERE endpoint = ? AND cached = 0 "
        "      ORDER BY recorded_at DESC LIMIT 10)",
        (endpoint,),
    ).fetchone()
    if row and row["cnt"] > 0:
        conn.close()
        return round(row["avg_dur"], 1)
    # Fallback: cached timings (just to have some number)
    row = conn.execute(
        "SELECT AVG(duration) as avg_dur, COUNT(*) as cnt "
        "FROM (SELECT duration FROM request_timing "
        "      WHERE endpoint = ? "
        "      ORDER BY recorded_at DESC LIMIT 10)",
        (endpoint,),
    ).fetchone()
    conn.close()
    if row is None or row["cnt"] == 0:
        return None
    return round(row["avg_dur"], 1)


def get_all_avg_durations():
    """Return a dict of endpoint -> avg duration for all known endpoints."""
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT endpoint FROM request_timing WHERE cached = 0"
    ).fetchall()
    result = {}
    for r in rows:
        ep = r["endpoint"]
        avg_row = conn.execute(
            "SELECT AVG(duration) as avg_dur "
            "FROM (SELECT duration FROM request_timing "
            "      WHERE endpoint = ? AND cached = 0 "
            "      ORDER BY recorded_at DESC LIMIT 10)",
            (ep,),
        ).fetchone()
        if avg_row and avg_row["avg_dur"] is not None:
            result[ep] = round(avg_row["avg_dur"], 1)
    conn.close()
    return result


def get_cache_status():
    """Return a dict with fetched_at timestamps for every cached key.

    Returns: { cache_key: { "fetchedAt": ISO str, "ageMinutes": float, "fresh": bool } }
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT cache_key, fetched_at FROM app_cache"
    ).fetchall()
    kw_rows = conn.execute(
        "SELECT cache_key, fetched_at FROM keyword_cache"
    ).fetchall()
    conn.close()

    now = datetime.utcnow()
    result = {}
    for r in list(rows) + list(kw_rows):
        key = r["cache_key"]
        fetched = datetime.fromisoformat(r["fetched_at"])
        age_min = (now - fetched).total_seconds() / 60.0
        fresh = age_min < CACHE_TTL_HOURS * 60
        result[key] = {
            "fetchedAt": r["fetched_at"],
            "ageMinutes": round(age_min, 1),
            "fresh": fresh,
        }
    return result


def get_all_cached_apps():
    """Return ALL cached app data keyed by cache_key (ignoring TTL).

    Returns: { cache_key: [app_dicts, ...] }
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT cache_key, app_data, fetched_at FROM app_cache"
    ).fetchall()
    conn.close()

    result = {}
    for r in rows:
        result[r["cache_key"]] = {
            "apps": json.loads(r["app_data"]),
            "fetchedAt": r["fetched_at"],
        }
    return result


# ---------------------------------------------------------------------------
# Custom niches
# ---------------------------------------------------------------------------

def save_custom_niche(niche_name, keywords):
    """Save a custom niche with its keyword seeds. Overwrites if exists."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO custom_niches (niche_name, keywords, created_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(niche_name) DO UPDATE SET keywords = excluded.keywords",
        (niche_name, json.dumps(keywords), now),
    )
    conn.commit()
    conn.close()


def get_custom_niches():
    """Return all custom niches as a dict: { name: [keywords] }."""
    conn = _connect()
    rows = conn.execute("SELECT niche_name, keywords FROM custom_niches").fetchall()
    conn.close()
    return {r["niche_name"]: json.loads(r["keywords"]) for r in rows}


def delete_custom_niche(niche_name):
    """Delete a custom niche by name. Returns True if it existed."""
    conn = _connect()
    cursor = conn.execute(
        "DELETE FROM custom_niches WHERE niche_name = ?", (niche_name,)
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Custom categories
# ---------------------------------------------------------------------------

def save_custom_category(category_name, queries, emoji="📂"):
    """Save a custom category (list of search queries). Overwrites if exists."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO custom_categories (category_name, queries, emoji, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(category_name) DO UPDATE SET queries = excluded.queries, emoji = excluded.emoji",
        (category_name, json.dumps(queries), emoji, now),
    )
    conn.commit()
    conn.close()


def get_custom_categories():
    """Return all custom categories as a list of dicts.
    Each dict: { name, queries: [...], emoji }"""
    conn = _connect()
    rows = conn.execute(
        "SELECT category_name, queries, emoji FROM custom_categories"
    ).fetchall()
    conn.close()
    return [
        {"name": r["category_name"], "queries": json.loads(r["queries"]), "emoji": r["emoji"]}
        for r in rows
    ]


def delete_custom_category(category_name):
    """Delete a custom category by name. Returns True if it existed."""
    conn = _connect()
    cursor = conn.execute(
        "DELETE FROM custom_categories WHERE category_name = ?", (category_name,)
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# App notes & bookmarks
# ---------------------------------------------------------------------------

def save_note(app_id, note_text="", bookmarked=0):
    """Save or update a note/bookmark for an app."""
    conn = _connect()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO app_notes (app_id, note_text, bookmarked, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(app_id) DO UPDATE SET note_text = excluded.note_text, "
        "bookmarked = excluded.bookmarked, updated_at = excluded.updated_at",
        (app_id, note_text, 1 if bookmarked else 0, now, now),
    )
    conn.commit()
    conn.close()


def get_note(app_id):
    """Return note dict for an app, or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT app_id, note_text, bookmarked, created_at, updated_at "
        "FROM app_notes WHERE app_id = ?", (app_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "appId": row["app_id"],
        "note": row["note_text"],
        "bookmarked": bool(row["bookmarked"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_all_bookmarks():
    """Return all bookmarked/noted apps."""
    conn = _connect()
    rows = conn.execute(
        "SELECT app_id, note_text, bookmarked, created_at, updated_at "
        "FROM app_notes WHERE bookmarked = 1 OR note_text != '' "
        "ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "appId": r["app_id"],
            "note": r["note_text"],
            "bookmarked": bool(r["bookmarked"]),
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


def delete_note(app_id):
    """Delete note for an app. Returns True if it existed."""
    conn = _connect()
    cursor = conn.execute("DELETE FROM app_notes WHERE app_id = ?", (app_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Initialise on import
# ---------------------------------------------------------------------------
init_db()
