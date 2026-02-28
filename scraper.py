"""
Google Play Store scraper module.
Fetches the most popular/downloaded apps and returns structured data.
Includes request throttling to avoid IP bans and SQLite caching.
"""

import os
import time
import random
import math
import google_play_scraper as gps
from google_play_scraper.exceptions import ExtraHTTPError, NotFoundError
from dotenv import load_dotenv
from database import (
    get_cached_apps, save_apps,
    get_cached_keywords, save_keywords,
    log_query, seconds_since_last_query,
    get_custom_niches,
    get_custom_categories,
)


# ══════════════════════════════════════════════════════════════
# Human-like HTTP layer  (monkey-patches google_play_scraper)
# ══════════════════════════════════════════════════════════════
# The library uses bare urllib with NO headers, which Google
# instantly fingerprints as a bot.  We patch the low-level
# _urlopen / get functions to rotate real-browser headers.
# ──────────────────────────────────────────────────────────────

_USER_AGENTS = [
    # Chrome – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome – Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Firefox – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Edge – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome – Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-GB,en;q=0.9,en-US;q=0.8",
    "en-US,en;q=0.9,fr;q=0.7",
    "en,en-US;q=0.9,de;q=0.7",
]

def _build_browser_headers():
    """Return a dict of headers that mimic a real browser visit."""
    ua = random.choice(_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;"
                  "q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
        "Referer": "https://play.google.com/",
    }


# ══════════════════════════════════════════════════════════════
# Proxy rotation
# ══════════════════════════════════════════════════════════════

load_dotenv()   # reads .env into os.environ

def _load_proxies():
    """Parse the PROXIES env var into a list of proxy URLs."""
    raw = os.getenv("PROXIES", "").strip()
    if not raw:
        return []
    proxies = [p.strip() for p in raw.split(",") if p.strip()]
    if proxies:
        print(f"  [PROXY] Loaded {len(proxies)} proxy(ies)")
    return proxies

_proxy_pool = _load_proxies()
_dead_proxies = set()          # temporarily skip proxies that fail
_PROXY_TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "10"))

def _pick_proxy():
    """Return the next live proxy URL, or None for direct connection."""
    if not _proxy_pool:
        return None
    alive = [p for p in _proxy_pool if p not in _dead_proxies]
    if not alive:
        # All dead — reset and try again
        _dead_proxies.clear()
        alive = list(_proxy_pool)
        print("  [PROXY] All proxies were dead — resetting pool")
    return random.choice(alive)

def _mark_proxy_dead(proxy_url):
    """Temporarily remove a proxy from rotation."""
    _dead_proxies.add(proxy_url)
    alive = len(_proxy_pool) - len(_dead_proxies)
    print(f"  [PROXY] Marked dead: {proxy_url}  ({alive} remaining)")

def get_proxy_status():
    """Return proxy pool info (used by the /api/proxy-status endpoint)."""
    return {
        "total": len(_proxy_pool),
        "alive": len(_proxy_pool) - len(_dead_proxies),
        "dead": list(_dead_proxies),
        "usingProxies": len(_proxy_pool) > 0,
    }


def _patched_urlopen(url_or_request):
    """Drop-in replacement for the library's _urlopen.
    Adds browser headers and optional proxy support."""
    from urllib.request import Request, urlopen, ProxyHandler, build_opener
    from urllib.error import HTTPError, URLError
    import ssl, gzip

    ssl._create_default_https_context = ssl._create_unverified_context

    # Build the Request object with browser headers
    if isinstance(url_or_request, str):
        req = Request(url_or_request, headers=_build_browser_headers())
    else:
        req = url_or_request
        for k, v in _build_browser_headers().items():
            if not req.has_header(k):
                req.add_header(k, v)

    proxy = _pick_proxy()

    try:
        if proxy:
            # Route through the chosen proxy
            scheme = "https" if req.full_url.startswith("https") else "http"
            handler = ProxyHandler({scheme: proxy, "http": proxy, "https": proxy})
            opener = build_opener(handler)
            resp = opener.open(req, timeout=_PROXY_TIMEOUT)
        else:
            resp = urlopen(req, timeout=_PROXY_TIMEOUT)
    except HTTPError as e:
        if e.code == 404:
            raise NotFoundError("App not found(404).")
        else:
            raise ExtraHTTPError(
                "App not found. Status code {} returned.".format(e.code)
            )
    except (URLError, OSError, ConnectionError, TimeoutError) as e:
        # Network-level failure — mark this proxy dead and retry direct
        if proxy:
            _mark_proxy_dead(proxy)
            # Retry once without proxy (or with another proxy)
            return _patched_urlopen(url_or_request)
        raise ExtraHTTPError(f"Network error: {e}") from e

    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("UTF-8")

# Apply the monkey-patch
import google_play_scraper.utils.request as _gps_req
_gps_req._urlopen = _patched_urlopen
_gps_req.get = lambda url: _patched_urlopen(url)


class IPBlockedError(Exception):
    """Raised when Google Play appears to have blocked our IP."""
    pass


class CancelledError(Exception):
    """Raised when a scraping operation is cancelled (user switched tabs)."""
    pass


def _check_cancelled(cancel_event):
    """Raise CancelledError if the cancel event is set."""
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("Scraping cancelled by client")


def _check_blocked(exc):
    """Inspect an exception and raise IPBlockedError if it looks like a ban."""
    msg = str(exc).lower()
    blocked_signals = ["429", "too many", "rate limit", "blocked", "forbidden",
                       "captcha", "unusual traffic", "denied"]
    if any(s in msg for s in blocked_signals):
        raise IPBlockedError(
            "Google Play has temporarily blocked requests from this IP. "
            "Please wait a few minutes before trying again."
        ) from exc
    if isinstance(exc, ExtraHTTPError):
        raise IPBlockedError(
            "Google Play returned an unexpected HTTP error, which usually "
            "means the IP has been rate-limited. Wait a few minutes."
        ) from exc

# ── Throttle settings ────────────────────────────────────
# Every single request to Google Play must respect a minimum gap.
# This is enforced via the database query_log, so even concurrent
# Flask requests (different tabs) cannot bypass it.
MIN_DELAY = 10          # minimum seconds between ANY Google Play request
MAX_DELAY = 16          # upper cap
SESSION_COOLDOWN = 90   # seconds between batch scraping sessions
_consecutive_errors = 0  # for exponential backoff
import threading
_throttle_lock = threading.Lock()

def _interruptible_sleep(seconds, cancel_event=None):
    """Sleep that can be interrupted by a cancel event.
    Checks the event every 0.5s instead of blocking for the full duration."""
    if cancel_event is None:
        time.sleep(seconds)
        return
    end = time.time() + seconds
    while time.time() < end:
        if cancel_event.is_set():
            raise CancelledError("Scraping cancelled by client")
        time.sleep(min(0.5, end - time.time()))


def _throttle(cancel_event=None):
    """Enforce a global minimum gap between requests.

    Uses the database query_log so that even concurrent Flask
    requests (user switching tabs fast) are serialised.
    If cancel_event is set, raises CancelledError immediately.
    """
    global _consecutive_errors
    _check_cancelled(cancel_event)

    with _throttle_lock:
        # Check how long since the LAST request (any type)
        elapsed = seconds_since_last_query()
        if elapsed is not None and elapsed < MIN_DELAY:
            wait = MIN_DELAY - elapsed
            # Add human jitter (0-3s extra)
            wait += random.uniform(0, 3.0)
            print(f"  [THROTTLE] Last request was {elapsed:.1f}s ago. "
                  f"Waiting {wait:.1f}s…")
            _interruptible_sleep(wait, cancel_event)
        else:
            # Still add a small human-like pause (1-4s)
            _interruptible_sleep(random.uniform(1.0, 4.0), cancel_event)

        # 12% chance of a longer "reading" pause (5-10s)
        if random.random() < 0.12:
            extra = random.uniform(5.0, 10.0)
            print(f"  [PAUSE] Reading pause +{extra:.1f}s")
            _interruptible_sleep(extra, cancel_event)

        # Exponential backoff when errors are piling up
        if _consecutive_errors > 0:
            backoff = min(2 ** _consecutive_errors, 60)
            print(f"  [BACKOFF] +{backoff}s (error streak: {_consecutive_errors})")
            _interruptible_sleep(backoff, cancel_event)

def _record_success():
    global _consecutive_errors
    _consecutive_errors = 0

def _record_error():
    global _consecutive_errors
    _consecutive_errors += 1


def _enforce_session_cooldown(cancel_event=None):
    """If we scraped recently, wait until the cooldown period has passed."""
    _check_cancelled(cancel_event)
    elapsed = seconds_since_last_query()
    if elapsed is not None and elapsed < SESSION_COOLDOWN:
        wait = SESSION_COOLDOWN - elapsed
        print(f"  [COOLDOWN] Last query was {elapsed:.0f}s ago. Waiting {wait:.0f}s…")
        _interruptible_sleep(wait, cancel_event)


def search_top_apps(query, count=100, country="us", lang="en", cancel_event=None):
    """Search Google Play and return up to `count` results."""
    _throttle(cancel_event)
    _check_cancelled(cancel_event)
    try:
        results = gps.search(query, lang=lang, country=country, n_hits=count)
        log_query("search", query)
        _record_success()
        return results
    except CancelledError:
        raise
    except Exception as e:
        _record_error()
        _check_blocked(e)
        print(f"  [!] Search failed for '{query}': {e}")
        return []


def get_app_details(app_id, country="us", lang="en", cancel_event=None):
    """Return full details for a single app by its package id."""
    _throttle(cancel_event)
    _check_cancelled(cancel_event)
    try:
        details = gps.app(app_id, lang=lang, country=country)
        log_query("detail", app_id)
        _record_success()
        return details
    except CancelledError:
        raise
    except Exception as e:
        _record_error()
        _check_blocked(e)
        return None


def _parse_installs(installs_str):
    """Convert an installs string like '100,000,000+' to an integer."""
    if isinstance(installs_str, (int, float)):
        return int(installs_str)
    if not installs_str:
        return 0
    return int(installs_str.replace(",", "").replace("+", "").strip() or 0)


def deduplicate(apps_list):
    """Remove duplicate apps (by appId) while preserving order."""
    seen = set()
    unique = []
    for a in apps_list:
        aid = a.get("appId")
        if aid and aid not in seen:
            seen.add(aid)
            unique.append(a)
    return unique


def enrich_apps(apps_list, country="us", lang="en", cancel_event=None):
    """Fetch full details for each app (installs, ratings, genre, etc.)."""
    enriched = []
    for a in apps_list:
        _check_cancelled(cancel_event)
        aid = a.get("appId")
        if not aid:
            continue
        details = get_app_details(aid, country=country, lang=lang, cancel_event=cancel_event)
        if details:
            enriched.append(details)
        else:
            enriched.append(a)
    return enriched


# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

GENERAL_QUERIES = [
    "top free apps",
    "popular apps 2026",
    "trending apps",
    "most downloaded apps",
    "best new apps",
    "top apps this week",
    "popular free apps",
]

CATEGORY_QUERIES = {
    # ── Original categories ──
    "Games":            ["popular games", "top free games", "trending games", "best mobile games"],
    "Social":           ["popular social media apps", "top social apps"],
    "Entertainment":    ["popular streaming apps", "entertainment apps", "top video apps"],
    "Productivity":     ["popular productivity apps", "best productivity tools"],
    "Anime":            [
        "anime apps", "anime streaming", "anime games",
        "watch anime", "anime manga", "best anime app",
        "anime wallpaper", "anime drawing",
    ],
    "Health":           ["health apps", "fitness apps", "workout apps", "calorie tracker", "meditation apps"],
    "Finance":          ["finance apps", "budget apps", "investing apps", "crypto wallet", "banking apps"],
    "Education":        ["education apps", "learning apps", "language learning", "study apps", "online courses"],
    "AI":               ["ai apps", "ai assistant", "ai chat", "ai image generator", "chatgpt", "ai tools"],
    "Crypto":           ["crypto apps", "bitcoin", "cryptocurrency", "nft apps", "defi wallet", "crypto trading"],
    "Shopping":         ["shopping apps", "online shopping", "deals apps", "coupon apps"],
    "Food":             ["food delivery apps", "recipe apps", "cooking apps", "meal planner"],
    "Travel":           ["travel apps", "hotel booking", "flight booking", "trip planner"],
    "Music":            ["music apps", "music streaming", "podcast apps", "music player"],
    "Photography":      ["photo editor", "camera apps", "photo filter", "video editor"],
    # ── Additional Google Play categories ──
    "Art & Design":     ["art apps", "drawing apps", "design apps", "coloring apps", "sketch apps"],
    "Auto & Vehicles":  ["car apps", "vehicle apps", "driving apps", "car maintenance", "auto insurance"],
    "Beauty":           ["beauty apps", "makeup apps", "skincare apps", "hairstyle apps", "nail art apps"],
    "Books & Reference":["ebook reader", "audiobooks", "dictionary apps", "library apps", "pdf reader"],
    "Business":         ["business apps", "crm apps", "invoice apps", "project management", "meeting apps"],
    "Comics":           ["comics app", "manga reader", "webtoon", "comic book reader", "webcomic apps"],
    "Communication":    ["messaging apps", "chat apps", "video call apps", "email apps", "walkie talkie"],
    "Dating":           ["dating apps", "matchmaking apps", "relationship apps", "singles apps"],
    "Events":           ["event apps", "ticketing apps", "event planner", "concert apps", "meetup apps"],
    "House & Home":     ["home design apps", "interior design", "real estate apps", "smart home", "furniture apps"],
    "Libraries & Demo": ["demo apps", "library apps", "sample apps", "developer tools"],
    "Lifestyle":        ["lifestyle apps", "daily routine", "horoscope apps", "journal apps", "quotes apps"],
    "Maps & Navigation":["maps apps", "gps navigation", "offline maps", "traffic apps", "compass apps"],
    "Medical":          ["medical apps", "symptom checker", "pill reminder", "doctor apps", "telehealth apps"],
    "News & Magazines": ["news apps", "breaking news", "magazine apps", "newspaper apps", "rss reader"],
    "Parenting":        ["parenting apps", "baby tracker", "pregnancy apps", "kids safety", "family apps"],
    "Personalization":  ["wallpaper apps", "launcher apps", "icon packs", "widget apps", "theme apps"],
    "Sports":           ["sports apps", "live scores", "fantasy sports", "sports news", "workout tracker"],
    "Tools":            ["utility apps", "file manager", "calculator apps", "flashlight", "qr scanner"],
    "Video Players":    ["video player", "media player", "movie apps", "streaming player", "video downloader"],
    "Weather":          ["weather apps", "weather forecast", "weather radar", "storm tracker", "weather widget"],
}

# Anime-related search keywords to probe Google Play for popularity
ANIME_KEYWORD_SEEDS = [
    "anime",
    "anime streaming",
    "anime games",
    "anime wallpaper",
    "anime drawing",
    "anime manga",
    "watch anime free",
    "anime avatar maker",
    "anime music",
    "anime chat",
    "anime tv",
    "anime rpg",
    "crunchyroll",
    "funimation",
    "anime stickers",
    "manga reader",
    "anime filter",
    "anime photo editor",
    "anime quiz",
    "anime radio",
]

# ── Multi-niche keyword seeds ────────────────────────────────
# Each key is a niche name; values are keyword probes to gauge demand.
NICHE_KEYWORD_SEEDS = {
    "Anime": ANIME_KEYWORD_SEEDS,
    "Health & Fitness": [
        "fitness tracker", "workout planner", "yoga app", "calorie counter",
        "step counter", "home workout", "gym tracker", "meditation",
        "sleep tracker", "running app", "diet plan", "fasting app",
        "mental health", "habit tracker", "water reminder",
    ],
    "Finance & Crypto": [
        "budget tracker", "expense manager", "investing app", "stock trading",
        "crypto wallet", "bitcoin", "tax calculator", "savings app",
        "money transfer", "credit score", "personal finance", "defi",
        "nft marketplace", "forex trading", "payment app",
    ],
    "AI Tools": [
        "ai assistant", "chatgpt", "ai image generator", "ai art",
        "ai writing", "ai chat", "ai photo editor", "ai voice",
        "ai translate", "ai homework", "ai music", "text to image",
        "ai avatar", "ai video", "ai keyboard",
    ],
    "Education": [
        "language learning", "math solver", "flashcards", "online courses",
        "coding app", "kids learning", "dictionary", "ebook reader",
        "study planner", "exam preparation", "typing tutor", "science app",
        "quiz app", "homework help", "audiobooks",
    ],
    "Food & Cooking": [
        "recipe app", "meal planner", "food delivery", "cooking timer",
        "calorie tracker", "grocery list", "restaurant finder",
        "keto recipes", "vegan recipes", "baking app", "cocktail recipes",
        "food scanner", "diet app", "intermittent fasting", "nutrition",
    ],
    "Travel": [
        "flight booking", "hotel booking", "travel planner", "maps offline",
        "translate app", "currency converter", "packing list",
        "road trip", "vacation rental", "city guide", "travel insurance",
        "train tickets", "camping app", "hiking trails", "scuba diving",
    ],
    "Photography": [
        "photo editor", "camera filter", "collage maker", "video editor",
        "photo to cartoon", "background remover", "photo frame",
        "slow motion video", "time lapse", "panorama", "photo recovery",
        "watermark app", "meme maker", "gif maker", "screen recorder",
    ],
    "Music": [
        "music player", "music streaming", "podcast app", "radio app",
        "karaoke app", "music maker", "beat maker", "guitar tuner",
        "piano app", "dj app", "lyrics app", "music downloader",
        "ringtone maker", "sound effects", "audiobook app",
    ],
}


def get_all_niche_seeds():
    """Return all niche keyword seeds: built-in + custom from DB."""
    merged = dict(NICHE_KEYWORD_SEEDS)
    merged.update(get_custom_niches())
    return merged


def get_all_categories():
    """Return all category query mappings: built-in + custom from DB.
    Returns dict  { category_name: [query_strings] }.
    """
    merged = dict(CATEGORY_QUERIES)
    for cat in get_custom_categories():
        merged[cat["name"]] = cat["queries"]
    return merged


def fetch_general_top(count=100, country="us", lang="en", cancel_event=None):
    """Return the top `count` most-downloaded general apps.
    Results are stored in / served from the SQLite database."""
    cache_key = f"general_top_{count}_{country}_{lang}"
    cached = get_cached_apps(cache_key)
    if cached is not None:
        print(f"  [DB] Serving general top from database ({len(cached)} apps)")
        return cached

    print("  [SCRAPE] Fetching general top from Google Play…")
    _enforce_session_cooldown(cancel_event)
    all_results = []
    queries = list(GENERAL_QUERIES)
    random.shuffle(queries)
    for q in queries:
        _check_cancelled(cancel_event)
        all_results.extend(search_top_apps(q, count=count, country=country, lang=lang, cancel_event=cancel_event))

    all_results = deduplicate(all_results)[:count]
    # Derive realInstalls from the installs string when not already present
    for a in all_results:
        if "realInstalls" not in a:
            a["realInstalls"] = _parse_installs(a.get("installs", "0"))
    all_results.sort(key=lambda a: a.get("realInstalls", 0), reverse=True)
    result = all_results[:count]
    save_apps(cache_key, result)
    return result


def fetch_category_top(category_name, count=100, country="us", lang="en", cancel_event=None):
    """Return the top `count` apps for a specific category.
    Results are stored in / served from the SQLite database."""
    cache_key = f"cat_{category_name}_{count}_{country}_{lang}"
    cached = get_cached_apps(cache_key)
    if cached is not None:
        print(f"  [DB] Serving {category_name} from database ({len(cached)} apps)")
        return cached

    print(f"  [SCRAPE] Fetching {category_name} from Google Play…")
    _enforce_session_cooldown(cancel_event)
    all_cats = get_all_categories()
    queries = list(all_cats.get(category_name, []))
    random.shuffle(queries)
    cat_results = []
    for q in queries:
        _check_cancelled(cancel_event)
        cat_results.extend(search_top_apps(q, count=count, country=country, lang=lang, cancel_event=cancel_event))

    cat_results = deduplicate(cat_results)[:count]
    # Derive realInstalls from the installs string when not already present
    for a in cat_results:
        if "realInstalls" not in a:
            a["realInstalls"] = _parse_installs(a.get("installs", "0"))
    cat_results.sort(key=lambda a: a.get("realInstalls", 0), reverse=True)
    result = cat_results[:count]
    save_apps(cache_key, result)
    return result


def fetch_anime_keywords(country="us", lang="en", cancel_event=None):
    """Return anime-related keywords ranked by result count on Google Play.
    Results are stored in / served from the SQLite database."""
    return fetch_niche_keywords("Anime", country=country, lang=lang, cancel_event=cancel_event)


def fetch_niche_keywords(niche_name, country="us", lang="en", cancel_event=None):
    """Return keywords for any niche ranked by result count.
    Results are stored in / served from the SQLite database."""
    all_seeds = get_all_niche_seeds()
    seeds = all_seeds.get(niche_name, [])
    if not seeds:
        return []

    cache_key = f"niche_kw_{niche_name}_{country}_{lang}"
    cached = get_cached_keywords(cache_key)
    if cached is not None:
        print(f"  [DB] Serving {niche_name} keywords from database ({len(cached)} kw)")
        return cached

    print(f"  [SCRAPE] Fetching {niche_name} keywords from Google Play…")
    _enforce_session_cooldown(cancel_event)
    keyword_results = []
    shuffled_seeds = list(seeds)
    random.shuffle(shuffled_seeds)
    for kw in shuffled_seeds:
        _check_cancelled(cancel_event)
        _throttle(cancel_event)
        _check_cancelled(cancel_event)
        try:
            results = gps.search(kw, lang=lang, country=country, n_hits=30)
            _record_success()
            keyword_results.append({
                "keyword": kw,
                "resultCount": len(results),
            })
        except CancelledError:
            raise
        except Exception as e:
            _record_error()
            _check_blocked(e)
            print(f"  [!] Keyword probe failed for '{kw}': {e}")
            keyword_results.append({"keyword": kw, "resultCount": 0})
    keyword_results.sort(key=lambda k: k["resultCount"], reverse=True)
    save_keywords(cache_key, keyword_results)
    return keyword_results


def compute_niche_score(niche_name, country="us", lang="en", cancel_event=None):
    """Compute an opportunity score for a niche.

    The score considers:
      - keyword_demand   : avg result count per keyword (higher = more demand)
      - saturation        : how many top-30 apps have 10M+ installs (higher = harder)
      - gap_score         : avg count of top-30 apps with rating < 4.0 (higher = opportunity)
      - freshness         : % of top apps released in last 12 months (trending signal)
    Returns a dict with individual metrics + a combined opportunity score 0-100.
    """
    from datetime import datetime, timedelta

    # 1. Keyword demand
    kw_data = fetch_niche_keywords(niche_name, country=country, lang=lang, cancel_event=cancel_event)
    avg_results = sum(k["resultCount"] for k in kw_data) / max(len(kw_data), 1)

    _check_cancelled(cancel_event)

    # 2. Grab apps for analysis — try matching category first, else search keywords
    cat_key = None
    for k in CATEGORY_QUERIES:
        if niche_name.lower() in k.lower() or k.lower() in niche_name.lower():
            cat_key = k
            break

    apps = []
    if cat_key and cat_key in CATEGORY_QUERIES:
        apps = fetch_category_top(cat_key, count=30, country=country, lang=lang, cancel_event=cancel_event)
    else:
        # No matching category — search using the niche's own keywords
        all_seeds = get_all_niche_seeds()
        seeds = all_seeds.get(niche_name, [])
        search_kws = seeds[:5]  # use up to 5 keywords to build an app pool
        seen_ids = set()
        for sq in search_kws:
            _check_cancelled(cancel_event)
            results = search_top_apps(sq, count=30, country=country, lang=lang, cancel_event=cancel_event)
            for r in results:
                aid = r.get("appId")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    # Ensure realInstalls is populated from search results
                    if not r.get("realInstalls") and r.get("installs"):
                        r["realInstalls"] = _parse_installs(r["installs"])
                    apps.append(r)
            if len(apps) >= 30:
                break
        apps = apps[:30]
        print(f"  [NICHE] Gathered {len(apps)} apps from keyword search for '{niche_name}'")

    total = max(len(apps), 1)

    # 3. Saturation: apps with 10M+ installs
    big_apps = sum(1 for a in apps if a.get("realInstalls", 0) >= 10_000_000)
    saturation_pct = (big_apps / total) * 100

    # 4. Gap: apps with score < 4.0
    low_rated = sum(1 for a in apps if (a.get("score") or 5) < 4.0)
    gap_pct = (low_rated / total) * 100

    # 5. Freshness: released in last 12 months
    cutoff = datetime.utcnow() - timedelta(days=365)
    fresh = 0
    for a in apps:
        rel = a.get("released", "")
        if rel:
            try:
                rd = datetime.strptime(rel, "%b %d, %Y")
                if rd >= cutoff:
                    fresh += 1
            except Exception:
                pass
    freshness_pct = (fresh / total) * 100

    # 6. Avg installs
    avg_installs = sum(a.get("realInstalls", 0) for a in apps) / total

    # 7. Combined opportunity score (0-100)
    demand_score = min(avg_results / 30 * 40, 40)        # max 40 pts
    gap_score    = min(gap_pct / 100 * 25, 25)            # max 25 pts
    fresh_score  = min(freshness_pct / 100 * 20, 20)      # max 20 pts
    sat_penalty  = min(saturation_pct / 100 * 25, 25)     # max -25 pts
    opportunity  = round(max(demand_score + gap_score + fresh_score + (25 - sat_penalty), 0), 1)

    return {
        "niche": niche_name,
        "keywordCount": len(kw_data),
        "avgResultsPerKeyword": round(avg_results, 1),
        "appsAnalysed": len(apps),
        "avgInstalls": int(avg_installs),
        "saturationPct": round(saturation_pct, 1),
        "gapPct": round(gap_pct, 1),
        "freshnessPct": round(freshness_pct, 1),
        "opportunityScore": opportunity,
    }


def serialize_app(app_dict):
    """Convert an app dict to a JSON-friendly dict with the fields we need."""
    return {
        "rank": None,  # filled in by caller
        "title": app_dict.get("title", "N/A"),
        "developer": app_dict.get("developer", "N/A"),
        "appId": app_dict.get("appId", ""),
        "score": round(app_dict["score"], 2) if app_dict.get("score") else None,
        "installs": app_dict.get("installs", "N/A"),
        "realInstalls": app_dict.get("realInstalls", 0),
        "icon": app_dict.get("icon", ""),
        "url": f"https://play.google.com/store/apps/details?id={app_dict.get('appId', '')}",
        "genre": app_dict.get("genre", ""),
        "free": app_dict.get("free", True),
        "price": app_dict.get("price", 0),
        "summary": (app_dict.get("summary") or "")[:200],
        "released": app_dict.get("released", ""),
        "description": app_dict.get("description", ""),
        "ratings": app_dict.get("ratings", 0),
        "reviews": app_dict.get("reviews", 0),
        "contentRating": app_dict.get("contentRating", ""),
        "lastUpdatedOn": app_dict.get("lastUpdatedOn", ""),
        "version": app_dict.get("version", ""),
        "developerEmail": app_dict.get("developerEmail", ""),
        "developerWebsite": app_dict.get("developerWebsite", ""),
        "headerImage": app_dict.get("headerImage", ""),
        "screenshots": (app_dict.get("screenshots") or [])[:5],
        "histogram": app_dict.get("histogram", []),
    }


# ---------------------------------------------------------------------------
# App comparison – description word analysis
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of is it this that with from by as are "
    "was were be been being have has had do does did will would shall should may "
    "might can could not no your you we our they them their its my me he she him "
    "her all any each every some more most other than so very just also about up "
    "out if into over after before between under again further then once here there "
    "when where why how which who whom what both few many much own same such too "
    "only through during above below while because until these those & app apps "
    "use new get one two make like best top".split()
)


def _extract_words(text):
    """Extract meaningful lowercased words from text."""
    import re
    words = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return [w for w in words if w not in _STOP_WORDS]


def _word_frequency(words):
    """Return a dict of word → count."""
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return freq


def compare_apps(app_id_1, app_id_2):
    """Compare two apps: description word overlap, unique words, stats."""
    d1 = get_app_details(app_id_1)
    d2 = get_app_details(app_id_2)
    if not d1 or not d2:
        return None

    a1 = serialize_app(d1)
    a2 = serialize_app(d2)

    words1 = _extract_words(a1["description"])
    words2 = _extract_words(a2["description"])
    freq1 = _word_frequency(words1)
    freq2 = _word_frequency(words2)

    set1 = set(freq1.keys())
    set2 = set(freq2.keys())

    shared = set1 & set2
    only1 = set1 - set2
    only2 = set2 - set1

    # Top shared words by combined frequency
    shared_ranked = sorted(shared, key=lambda w: freq1[w] + freq2[w], reverse=True)[:30]
    only1_ranked = sorted(only1, key=lambda w: freq1[w], reverse=True)[:20]
    only2_ranked = sorted(only2, key=lambda w: freq2[w], reverse=True)[:20]

    return {
        "app1": {
            "appId": a1["appId"], "title": a1["title"], "icon": a1["icon"],
            "developer": a1["developer"], "installs": a1["installs"],
            "realInstalls": a1["realInstalls"], "score": a1["score"],
            "ratings": a1["ratings"], "released": a1["released"],
            "genre": a1["genre"], "totalWords": len(words1),
            "uniqueWords": len(set1),
        },
        "app2": {
            "appId": a2["appId"], "title": a2["title"], "icon": a2["icon"],
            "developer": a2["developer"], "installs": a2["installs"],
            "realInstalls": a2["realInstalls"], "score": a2["score"],
            "ratings": a2["ratings"], "released": a2["released"],
            "genre": a2["genre"], "totalWords": len(words2),
            "uniqueWords": len(set2),
        },
        "sharedWords": [{"word": w, "countApp1": freq1[w], "countApp2": freq2[w]} for w in shared_ranked],
        "onlyApp1": [{"word": w, "count": freq1[w]} for w in only1_ranked],
        "onlyApp2": [{"word": w, "count": freq2[w]} for w in only2_ranked],
        "overlapPct": round(len(shared) / max(len(set1 | set2), 1) * 100, 1),
    }
