#!/usr/bin/env python3
# Final isolated validation. This imports fetchers only and never calls update_prices.main().

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
PRICES_FILE = ROOT / "prices.json"
sys.path.insert(0, str(SCRIPT_DIR))

from update_prices import fetch_fidelity, fetch_gold_xetra  # noqa: E402

TZ_MADRID = ZoneInfo("Europe/Madrid")


def validate_recent_date(value, *, max_age_days):
    day = datetime.fromisoformat(value).date()
    today = datetime.now(TZ_MADRID).date()
    if day > today:
        raise AssertionError(f"future price date: {value}")
    if today - day > timedelta(days=max_age_days):
        raise AssertionError(f"stale price date: {value}")


def main():
    before = PRICES_FILE.read_bytes()

    fidelity = fetch_fidelity()
    gold = fetch_gold_xetra()

    after = PRICES_FILE.read_bytes()
    if before != after:
        raise AssertionError("prices.json changed during read-only source validation")

    fidelity_price, fidelity_date, fidelity_source = fidelity[:3]
    gold_price, gold_date, gold_source = gold[:3]

    if not (10 < fidelity_price < 25):
        raise AssertionError(f"implausible Fidelity NAV: {fidelity_price}")
    validate_recent_date(fidelity_date, max_age_days=7)
    if "NAV" not in fidelity_source:
        raise AssertionError(f"Fidelity source is not identified as NAV: {fidelity_source}")

    if not (40 < gold_price < 120):
        raise AssertionError(f"implausible gold Xetra price: {gold_price}")
    validate_recent_date(gold_date, max_age_days=4)
    if "Xetra" not in gold_source:
        raise AssertionError(f"Gold source is not identified as Xetra: {gold_source}")

    print(json.dumps({
        "pricesJsonUnchanged": True,
        "Fidelity": {
            "price": fidelity_price,
            "priceDate": fidelity_date,
            "source": fidelity_source,
        },
        "Gold": {
            "price": gold_price,
            "priceDate": gold_date,
            "source": gold_source,
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
