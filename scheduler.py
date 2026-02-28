"""
Background scheduler – refreshes all categories every hour.

Run alongside (or instead of) the Flask app:
    python3 scheduler.py

Each cycle calls the same fetch functions used by the web UI.
If the cache is still fresh (< 6h old), the category is skipped
automatically, so running this more frequently than the TTL is safe.
"""

import time
import signal
import sys
from datetime import datetime

from scraper import (
    fetch_general_top,
    fetch_category_top,
    get_all_categories,
    IPBlockedError,
)
from database import CACHE_TTL_HOURS


# ── Config ────────────────────────────────────────────────────
INTERVAL_SECONDS = 3600          # 1 hour between full cycles
COUNT            = 100           # top N apps per category
COUNTRY          = "us"
LANG             = "en"


# ── Graceful shutdown ─────────────────────────────────────────
_stop = False

def _handle_signal(sig, frame):
    global _stop
    print("\n[SCHEDULER] Shutting down after current task…")
    _stop = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Main loop ─────────────────────────────────────────────────
def run_cycle():
    """Refresh General Top + every category (built-in + custom)."""
    categories = get_all_categories()
    total = 1 + len(categories)  # +1 for general top
    done  = 0
    errors = 0

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"[SCHEDULER] Cycle started at {ts}  ({total} targets)")
    print(f"{'='*60}")

    # 1. General Top
    if _stop:
        return done, errors
    try:
        print(f"\n[1/{total}] General Top 100")
        fetch_general_top(count=COUNT, country=COUNTRY, lang=LANG)
        done += 1
    except IPBlockedError as e:
        print(f"  ⚠ IP blocked – pausing 5 min: {e}")
        _safe_sleep(300)
        errors += 1
    except Exception as e:
        print(f"  ✗ Error: {e}")
        errors += 1

    # 2. Each category
    for i, cat_name in enumerate(categories, start=2):
        if _stop:
            break
        try:
            print(f"\n[{i}/{total}] {cat_name}")
            fetch_category_top(cat_name, count=COUNT, country=COUNTRY, lang=LANG)
            done += 1
        except IPBlockedError as e:
            print(f"  ⚠ IP blocked – pausing 5 min: {e}")
            _safe_sleep(300)
            errors += 1
        except Exception as e:
            print(f"  ✗ Error: {e}")
            errors += 1

    ts2 = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"[SCHEDULER] Cycle finished at {ts2}  "
          f"({done}/{total} OK, {errors} errors)")
    print(f"{'='*60}")
    return done, errors


def _safe_sleep(seconds):
    """Sleep in 1-second increments so SIGINT is caught quickly."""
    end = time.time() + seconds
    while time.time() < end and not _stop:
        time.sleep(1)


def main():
    print(f"[SCHEDULER] Starting – {INTERVAL_SECONDS}s interval, "
          f"cache TTL {CACHE_TTL_HOURS}h")
    print(f"[SCHEDULER] Press Ctrl+C to stop gracefully.\n")

    while not _stop:
        run_cycle()
        if _stop:
            break
        print(f"\n[SCHEDULER] Next cycle in {INTERVAL_SECONDS // 60} min. "
              f"Sleeping…")
        _safe_sleep(INTERVAL_SECONDS)

    print("[SCHEDULER] Stopped.")


if __name__ == "__main__":
    main()
