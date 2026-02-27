"""
Flask web server for the Google Play Top Apps dashboard.
Serves a frontend and exposes API endpoints that return scraped data.
"""

import csv
import io
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
    CATEGORY_QUERIES,
    NICHE_KEYWORD_SEEDS,
    IPBlockedError,
)
from database import (
    save_snapshot, get_snapshots, get_latest_two_snapshots,
)

app = Flask(__name__, static_folder="static")


@app.errorhandler(IPBlockedError)
def handle_ip_blocked(exc):
    """Return a 429 JSON response when the IP is blocked."""
    return jsonify({
        "error": str(exc),
        "blocked": True,
    }), 429


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


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/top")
def api_top():
    """Return top 100 most-downloaded apps (general)."""
    apps = fetch_general_top(count=100)
    data = []
    for i, a in enumerate(apps, start=1):
        entry = serialize_app(a)
        entry["rank"] = i
        data.append(entry)
    return jsonify({"title": "Top 100 Most Popular Apps", "apps": data})


@app.route("/api/category/<category_name>")
def api_category(category_name):
    """Return top 100 apps for a given category."""
    if category_name not in CATEGORY_QUERIES:
        return jsonify({"error": f"Unknown category: {category_name}"}), 404

    apps = fetch_category_top(category_name, count=100)
    data = []
    for i, a in enumerate(apps, start=1):
        entry = serialize_app(a)
        entry["rank"] = i
        data.append(entry)
    return jsonify({"title": f"Top {category_name} Apps", "apps": data})


@app.route("/api/categories")
def api_categories():
    """Return available category names."""
    return jsonify({"categories": list(CATEGORY_QUERIES.keys())})


@app.route("/api/anime/keywords")
def api_anime_keywords():
    """Return top searched anime-related keywords on Google Play."""
    keywords = fetch_anime_keywords()
    return jsonify({"title": "Top Anime Search Keywords on Google Play", "keywords": keywords})


@app.route("/api/anime/apps")
def api_anime_apps():
    """Return top anime apps from Google Play."""
    apps = fetch_category_top("Anime", count=100)
    data = []
    for i, a in enumerate(apps, start=1):
        entry = serialize_app(a)
        entry["rank"] = i
        data.append(entry)
    return jsonify({"title": "Top Anime Apps on Google Play", "apps": data})


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
    """Return list of available niches with keyword seeds."""
    return jsonify({"niches": list(NICHE_KEYWORD_SEEDS.keys())})


@app.route("/api/niche/<niche_name>/keywords")
def api_niche_keywords(niche_name):
    """Return keyword popularity data for a given niche."""
    if niche_name not in NICHE_KEYWORD_SEEDS:
        return jsonify({"error": f"Unknown niche: {niche_name}"}), 404
    kws = fetch_niche_keywords(niche_name)
    return jsonify({"title": f"{niche_name} – Top Keywords", "keywords": kws})


@app.route("/api/niche/<niche_name>/score")
def api_niche_score(niche_name):
    """Compute and return the opportunity score for a niche."""
    if niche_name not in NICHE_KEYWORD_SEEDS:
        return jsonify({"error": f"Unknown niche: {niche_name}"}), 404
    score = compute_niche_score(niche_name)
    return jsonify(score)


@app.route("/api/niche/scores")
def api_all_niche_scores():
    """Compute opportunity scores for ALL niches (may be slow on first run)."""
    scores = []
    for niche in NICHE_KEYWORD_SEEDS:
        scores.append(compute_niche_score(niche))
    scores.sort(key=lambda s: s["opportunityScore"], reverse=True)
    return jsonify({"title": "Niche Opportunity Scores", "scores": scores})


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@app.route("/api/export/<category_name>")
def api_export_csv(category_name):
    """Export apps for a category (or 'top') as a CSV download."""
    if category_name == "top":
        apps = fetch_general_top(count=100)
        filename = "top_100_apps.csv"
    elif category_name in CATEGORY_QUERIES:
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
