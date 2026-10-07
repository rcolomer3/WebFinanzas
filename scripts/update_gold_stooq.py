#!/usr/bin/env python3

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
PRICES_FILE = ROOT / "prices.json"
TZ_MADRID = ZoneInfo("Europe/Madrid")
URL = "https://stooq.com/q/d/l/?s=ppfb.de&i=d"


def main():
    data = json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    asset = data["assets"]["IE00B4ND3602"]

    try:
        response = requests.get(
            URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=25,
        )
        response.raise_for_status()

        rows = list(csv.DictReader(io.StringIO(response.text)))
        rows = [row for row in rows if row.get("Date") and row.get("Close")]
        if not rows:
            raise RuntimeError("Stooq returned no PPFB.DE rows")

        latest = rows[-1]
        price_date = datetime.strptime(latest["Date"], "%Y-%m-%d").date().isoformat()
        price = float(latest["Close"])

        if asset.get("priceDate") and price_date < asset["priceDate"]:
            print("Stooq returned an older gold quote; keeping existing value")
            return

        asset["price"] = round(price, 8)
        asset["priceDate"] = price_date
        asset["source"] = "Stooq - Xetra (PPFB.DE)"
        data["updatedAt"] = datetime.now(TZ_MADRID).isoformat(timespec="seconds")
        PRICES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Gold updated from Stooq: {price} EUR ({price_date})")
    except Exception as exc:
        print(f"Stooq gold fallback unavailable; keeping existing value: {exc}")


if __name__ == "__main__":
    main()
