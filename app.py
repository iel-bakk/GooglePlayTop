"""
Flask web server for the Google Play Top Apps dashboard.
Serves a frontend and exposes API endpoints that return scraped data.
"""

import csv
import io
import time as _time
import threading
from flask import Flask, jsonify, send_from_directory, Response, request
from scraper import (
    fetch_general_top,
    fetch_category_top,
    fetch_anime_keywords,
    fetch_niche_keywords,
    compute_niche_score,
    compare_apps,
    get_app_details,
    serialize_app,
    get_proxy_status,
    get_all_niche_seeds,
    get_all_categories,
    CATEGORY_QUERIES,
    NICHE_KEYWORD_SEEDS,
    IPBlockedError,
    CancelledError,
    MIN_DELAY,
    SESSION_COOLDOWN,
)
from database import (
    save_snapshot, get_snapshots, get_latest_two_snapshots,
    seconds_since_last_query,
    log_request_timing, get_avg_duration, get_all_avg_durations,
    get_cache_status, CACHE_TTL_HOURS,
    save_custom_niche, get_custom_niches, delete_custom_niche,
    save_custom_category, get_custom_categories, delete_custom_category,
)

app = Flask(__name__, static_folder="static")


# ---------------------------------------------------------------------------
# Active-task registry: cancel previous scrapes when the user switches tabs
# ---------------------------------------------------------------------------
# Maps an endpoint group (e.g. "category", "top", "niche_scores") to the
# threading.Event used to cancel an in-flight scraping thread.
_active_tasks = {}       # group_key -> threading.Event
_active_tasks_lock = threading.Lock()


def _start_task(group_key):
    """Cancel any previous task for this group and return a new cancel Event."""
    cancel_event = threading.Event()
    with _active_tasks_lock:
        old = _active_tasks.get(group_key)
        if old is not None:
            old.set()  # signal the old task to stop
            print(f"  [CANCEL] Cancelled previous '{group_key}' scrape")
        _active_tasks[group_key] = cancel_event
    return cancel_event


def _finish_task(group_key, cancel_event):
    """Remove the task from the registry (only if it's still ours)."""
    with _active_tasks_lock:
        if _active_tasks.get(group_key) is cancel_event:
            del _active_tasks[group_key]


@app.errorhandler(IPBlockedError)
def handle_ip_blocked(exc):
    """Return a 429 JSON response when the IP is blocked."""
    return jsonify({
        "error": str(exc),
        "blocked": True,
    }), 429


@app.errorhandler(CancelledError)
def handle_cancelled(exc):
    """Return a 499 JSON response when the scrape was cancelled."""
    return jsonify({
        "error": "Request cancelled (newer request superseded this one)",
        "cancelled": True,
    }), 499


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/proxy-status")
def api_proxy_status():
    """Return current proxy pool health."""
    return jsonify(get_proxy_status())


@app.route("/api/cache-status")
def api_cache_status():
    """Return freshness info for every cached category / key."""
    raw = get_cache_status()
    # Build a user-friendly mapping: readable label -> status
    friendly = {}
    for key, info in raw.items():
        # Translate cache keys to readable names
        if key.startswith("general_top_"):
            label = "All (Top 100)"
        elif key.startswith("cat_"):
            parts = key.split("_", 2)  # cat_Anime_100_us_en
            label = parts[1] if len(parts) > 1 else key
        elif key.startswith("niche_kw_"):
            parts = key.split("_", 3)  # niche_kw_Anime_us_en
            label = parts[2] + " keywords" if len(parts) > 2 else key
        else:
            label = key
        friendly[label] = info
    return jsonify({"cache": friendly, "ttlHours": CACHE_TTL_HOURS})


@app.route("/api/throttle-status")
def api_throttle_status():
    """Return current throttle/cooldown state."""
    elapsed = seconds_since_last_query()
    if elapsed is None:
        return jsonify({"waiting": False, "waitSeconds": 0, "elapsed": None})

    wait_needed = MIN_DELAY - elapsed
    return jsonify({
        "waiting": wait_needed > 0,
        "waitSeconds": round(max(0, wait_needed), 1),
        "elapsed": round(elapsed, 1),
        "minDelay": MIN_DELAY,
        "sessionCooldown": SESSION_COOLDOWN,
    })


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/eta")
def api_eta():
    """Return estimated request durations based on past timings."""
    # Default estimates (seconds) for when there's no historical data yet.
    # Based on typical scraping durations: queries × ~12s delay + enrichment.
    _DEFAULTS = {
        "top": 120,                 # 7 search queries only (no enrichment)
        "anime:keywords": 250,      # 20 keyword probes
        "anime:apps": 60,           # 8 search queries only
    }
    # Category defaults: ~4 search queries ≈ 60s
    for cat in get_all_categories():
        _DEFAULTS[f"category:{cat}"] = 60

    endpoint = request.args.get("endpoint", "")
    if endpoint:
        avg = get_avg_duration(endpoint)
        if avg is None:
            avg = _DEFAULTS.get(endpoint)
        return jsonify({"endpoint": endpoint, "estimatedSeconds": avg})
    # Return all known durations (merge defaults with actuals)
    actuals = get_all_avg_durations()
    merged = {**_DEFAULTS, **actuals}
    return jsonify({"durations": merged})


@app.route("/api/top")
def api_top():
    """Return top 100 most-downloaded apps (general)."""
    cancel = _start_task("top")
    try:
        t0 = _time.time()
        apps = fetch_general_top(count=100, cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing("top", dur, cached=(dur < 2))
        data = []
        for i, a in enumerate(apps, start=1):
            entry = serialize_app(a)
            entry["rank"] = i
            data.append(entry)
        return jsonify({"title": "Top 100 Most Popular Apps", "apps": data})
    finally:
        _finish_task("top", cancel)


@app.route("/api/category/<category_name>")
def api_category(category_name):
    """Return top 100 apps for a given category."""
    all_cats = get_all_categories()
    if category_name not in all_cats:
        return jsonify({"error": f"Unknown category: {category_name}"}), 404

    cancel = _start_task("category")
    try:
        t0 = _time.time()
        apps = fetch_category_top(category_name, count=100, cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing(f"category:{category_name}", dur, cached=(dur < 2))
        data = []
        for i, a in enumerate(apps, start=1):
            entry = serialize_app(a)
            entry["rank"] = i
            data.append(entry)
        return jsonify({"title": f"Top {category_name} Apps", "apps": data})
    finally:
        _finish_task("category", cancel)


@app.route("/api/categories")
def api_categories():
    """Return available category names (built-in + custom)."""
    all_cats = get_all_categories()
    custom = get_custom_categories()
    custom_map = {c["name"]: c["emoji"] for c in custom}
    return jsonify({
        "categories": list(all_cats.keys()),
        "customCategories": custom_map,
    })


@app.route("/api/anime/keywords")
def api_anime_keywords():
    """Return top searched anime-related keywords on Google Play."""
    cancel = _start_task("anime")
    try:
        t0 = _time.time()
        keywords = fetch_anime_keywords(cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing("anime:keywords", dur, cached=(dur < 2))
        return jsonify({"title": "Top Anime Search Keywords on Google Play", "keywords": keywords})
    finally:
        _finish_task("anime", cancel)


@app.route("/api/anime/apps")
def api_anime_apps():
    """Return top anime apps from Google Play."""
    cancel = _start_task("anime")
    try:
        t0 = _time.time()
        apps = fetch_category_top("Anime", count=100, cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing("anime:apps", dur, cached=(dur < 2))
        data = []
        for i, a in enumerate(apps, start=1):
            entry = serialize_app(a)
            entry["rank"] = i
            data.append(entry)
        return jsonify({"title": "Top Anime Apps on Google Play", "apps": data})
    finally:
        _finish_task("anime", cancel)


@app.route("/api/app/<path:app_id>")
def api_app_detail(app_id):
    """Return full details for a single app by package id."""
    details = get_app_details(app_id)
    if not details:
        return jsonify({"error": f"App not found: {app_id}"}), 404
    return jsonify(serialize_app(details))


# ---------------------------------------------------------------------------
# Niche analysis
# ---------------------------------------------------------------------------

@app.route("/api/niches")
def api_niches():
    """Return list of available niches (built-in + custom) with keyword seeds."""
    all_seeds = get_all_niche_seeds()
    niches = []
    for name, seeds in all_seeds.items():
        niches.append({
            "name": name,
            "keywordCount": len(seeds),
            "builtin": name in NICHE_KEYWORD_SEEDS,
        })
    return jsonify({"niches": niches})


@app.route("/api/niche/custom", methods=["POST"])
def api_add_custom_niche():
    """Add a custom niche with keyword seeds.
    Body: { "name": "My Niche", "keywords": ["keyword1", "keyword2", ...] }
    """
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    keywords = data.get("keywords", [])

    if not name:
        return jsonify({"error": "Niche name is required"}), 400
    if not keywords or not isinstance(keywords, list):
        return jsonify({"error": "Provide a list of keyword strings"}), 400
    # Clean and validate keywords
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    if len(keywords) < 2:
        return jsonify({"error": "Provide at least 2 keywords"}), 400
    if len(keywords) > 30:
        return jsonify({"error": "Maximum 30 keywords allowed"}), 400

    save_custom_niche(name, keywords)
    return jsonify({"message": f"Niche '{name}' saved with {len(keywords)} keywords", "name": name})


@app.route("/api/niche/custom/<niche_name>", methods=["DELETE"])
def api_delete_custom_niche(niche_name):
    """Delete a custom niche by name."""
    if niche_name in NICHE_KEYWORD_SEEDS:
        return jsonify({"error": "Cannot delete built-in niches"}), 400
    if delete_custom_niche(niche_name):
        return jsonify({"message": f"Niche '{niche_name}' deleted"})
    return jsonify({"error": f"Niche '{niche_name}' not found"}), 404


# ---------------------------------------------------------------------------
# Custom categories
# ---------------------------------------------------------------------------

@app.route("/api/category/custom", methods=["POST"])
def api_add_custom_category():
    """Add a custom category with search queries.
    Body: { "name": "My Category", "queries": ["query1", "query2"], "emoji": "📂" }
    """
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    queries = data.get("queries", [])
    emoji = (data.get("emoji") or "📂").strip()

    if not name:
        return jsonify({"error": "Category name is required"}), 400
    if name in CATEGORY_QUERIES:
        return jsonify({"error": f"'{name}' is a built-in category and cannot be overridden"}), 400
    if not queries or not isinstance(queries, list):
        return jsonify({"error": "Provide a list of search query strings"}), 400
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    if len(queries) < 2:
        return jsonify({"error": "Provide at least 2 search queries"}), 400
    if len(queries) > 20:
        return jsonify({"error": "Maximum 20 search queries allowed"}), 400

    save_custom_category(name, queries, emoji)
    return jsonify({"message": f"Category '{name}' saved with {len(queries)} queries", "name": name})


@app.route("/api/category/custom/<category_name>", methods=["DELETE"])
def api_delete_custom_category(category_name):
    """Delete a custom category by name."""
    if category_name in CATEGORY_QUERIES:
        return jsonify({"error": "Cannot delete built-in categories"}), 400
    if delete_custom_category(category_name):
        return jsonify({"message": f"Category '{category_name}' deleted"})
    return jsonify({"error": f"Category '{category_name}' not found"}), 404


@app.route("/api/niche/<niche_name>/keywords")
def api_niche_keywords(niche_name):
    """Return keyword popularity data for a given niche."""
    all_seeds = get_all_niche_seeds()
    if niche_name not in all_seeds:
        return jsonify({"error": f"Unknown niche: {niche_name}"}), 404
    cancel = _start_task("niche")
    try:
        t0 = _time.time()
        kws = fetch_niche_keywords(niche_name, cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing(f"niche:{niche_name}", dur, cached=(dur < 2))
        return jsonify({"title": f"{niche_name} – Top Keywords", "keywords": kws})
    finally:
        _finish_task("niche", cancel)


@app.route("/api/niche/<niche_name>/score")
def api_niche_score(niche_name):
    """Compute and return the opportunity score for a niche."""
    all_seeds = get_all_niche_seeds()
    if niche_name not in all_seeds:
        return jsonify({"error": f"Unknown niche: {niche_name}"}), 404
    cancel = _start_task("niche")
    try:
        t0 = _time.time()
        score = compute_niche_score(niche_name, cancel_event=cancel)
        dur = _time.time() - t0
        log_request_timing(f"niche_score:{niche_name}", dur, cached=(dur < 2))
        return jsonify(score)
    finally:
        _finish_task("niche", cancel)


# Removed: /api/niche/scores (all-at-once) — use individual /api/niche/<name>/score instead


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@app.route("/api/export/<category_name>")
def api_export_csv(category_name):
    """Export apps for a category (or 'top') as a CSV download."""
    if category_name == "top":
        apps = fetch_general_top(count=100)
        filename = "top_100_apps.csv"
    elif category_name in get_all_categories():
        apps = fetch_category_top(category_name, count=100)
        filename = f"{category_name.lower()}_apps.csv"
    else:
        return jsonify({"error": f"Unknown category: {category_name}"}), 404

    fields = [
        "rank", "title", "developer", "appId", "genre", "score",
        "installs", "realInstalls", "released", "lastUpdatedOn",
        "free", "price", "contentRating", "url",
    ]

    si = io.StringIO()
    writer = csv.DictWriter(si, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for i, a in enumerate(apps, start=1):
        row = serialize_app(a)
        row["rank"] = i
        writer.writerow(row)

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Weekly snapshots
# ---------------------------------------------------------------------------

@app.route("/api/snapshot/save", methods=["POST"])
def api_save_snapshot():
    """Take a snapshot of current data for all categories + general top."""
    saved = []

    # General top
    apps = fetch_general_top(count=100)
    summary = [{"appId": a.get("appId"), "title": a.get("title"),
                "realInstalls": a.get("realInstalls", 0),
                "score": a.get("score")} for a in apps]
    save_snapshot("general_top", summary)
    saved.append("general_top")

    # Each category
    for cat in CATEGORY_QUERIES:
        apps = fetch_category_top(cat, count=30)
        summary = [{"appId": a.get("appId"), "title": a.get("title"),
                     "realInstalls": a.get("realInstalls", 0),
                     "score": a.get("score")} for a in apps]
        save_snapshot(f"cat_{cat}", summary)
        saved.append(f"cat_{cat}")

    return jsonify({"message": "Snapshots saved", "keys": saved})


@app.route("/api/snapshot/<snap_key>")
def api_get_snapshots(snap_key):
    """Return snapshot history for a key."""
    limit = request.args.get("limit", 10, type=int)
    snaps = get_snapshots(snap_key, limit=limit)
    return jsonify({"key": snap_key, "snapshots": snaps})


@app.route("/api/snapshot/<snap_key>/diff")
def api_snapshot_diff(snap_key):
    """Compare the two most recent snapshots and return changes."""
    snaps = get_latest_two_snapshots(snap_key)
    if len(snaps) < 2:
        return jsonify({"error": "Need at least 2 snapshots to compare", "available": len(snaps)}), 400

    current = {a["appId"]: a for a in snaps[0]["data"]}
    previous = {a["appId"]: a for a in snaps[1]["data"]}

    new_apps = [current[aid] for aid in current if aid not in previous]
    dropped  = [previous[aid] for aid in previous if aid not in current]

    install_changes = []
    for aid in current:
        if aid in previous:
            cur_inst = current[aid].get("realInstalls", 0)
            prev_inst = previous[aid].get("realInstalls", 0)
            if cur_inst != prev_inst:
                install_changes.append({
                    "appId": aid,
                    "title": current[aid].get("title"),
                    "previousInstalls": prev_inst,
                    "currentInstalls": cur_inst,
                    "change": cur_inst - prev_inst,
                })
    install_changes.sort(key=lambda x: x["change"], reverse=True)

    return jsonify({
        "key": snap_key,
        "currentDate": snaps[0]["takenAt"],
        "previousDate": snaps[1]["takenAt"],
        "newApps": new_apps,
        "droppedApps": dropped,
        "installChanges": install_changes[:20],
    })


# ---------------------------------------------------------------------------
# App comparison & install history
# ---------------------------------------------------------------------------

@app.route("/api/compare")
def api_compare():
    """Compare two apps by their descriptions and stats.
    Usage: /api/compare?app1=com.example.a&app2=com.example.b
    """
    app1 = request.args.get("app1", "")
    app2 = request.args.get("app2", "")
    if not app1 or not app2:
        return jsonify({"error": "Provide both app1 and app2 query params"}), 400

    result = compare_apps(app1, app2)
    if result is None:
        return jsonify({"error": "Could not fetch one or both apps"}), 404
    return jsonify(result)


@app.route("/api/install-history/<path:app_id>")
def api_install_history(app_id):
    """Return install counts for an app across all saved snapshots."""
    # Scan all snapshot keys for this app_id
    from database import _connect
    conn = _connect()
    rows = conn.execute(
        "SELECT snap_key, snap_data, taken_at FROM snapshots ORDER BY taken_at ASC"
    ).fetchall()
    conn.close()

    import json
    history = []
    for r in rows:
        data = json.loads(r["snap_data"])
        for app_entry in data:
            if app_entry.get("appId") == app_id:
                history.append({
                    "date": r["taken_at"],
                    "snapKey": r["snap_key"],
                    "realInstalls": app_entry.get("realInstalls", 0),
                    "score": app_entry.get("score"),
                })
                break

    return jsonify({
        "appId": app_id,
        "history": history,
    })


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
