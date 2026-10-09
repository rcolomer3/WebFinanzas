#!/usr/bin/env python3

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
PRICES_FILE = ROOT / "prices.json"
TZ_MADRID = ZoneInfo("Europe/Madrid")

INVESTING_URL = "https://es.investing.com/etfs/ishares-physical-gold-historical-data?cid=1198444"
STOOQ_URL = "https://stooq.com/q/d/l/?s=ppfb.de&i=d"
HEADERS = {
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def parse_number(value):
    return float(value.replace(".", "").replace(",", "."))


def fetch_investing():
    response = requests.get(INVESTING_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)

    candidates = []
    for date_text, value in re.findall(
        r"(\d{2}\.\d{2}\.\d{4})\s+([0-9]+(?:,[0-9]+)?)",
        text,
    ):
        try:
            date = datetime.strptime(date_text, "%d.%m.%Y").date()
            candidates.append((date, parse_number(value)))
        except ValueError:
            pass

    if not candidates:
        raise RuntimeError("Investing returned no PPFB Xetra rows")

    date, price = max(candidates, key=lambda item: item[0])
    return price, date.isoformat(), "Investing.com - Xetra"


def fetch_stooq():
    response = requests.get(STOOQ_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text)))
    rows = [row for row in rows if row.get("Date") and row.get("Close")]
    if not rows:
        raise RuntimeError("Stooq returned no PPFB.DE rows")
    latest = rows[-1]
    return float(latest["Close"]), latest["Date"], "Stooq - Xetra (PPFB.DE)"


def main():
    data = json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    asset = data["assets"]["IE00B4ND3602"]

    errors = []
    fetched = None

    for fetcher in (fetch_investing, fetch_stooq):
        try:
            fetched = fetcher()
            break
        except Exception as exc:
            errors.append(str(exc))

    if fetched is None:
        print("Gold fallback unavailable; keeping existing value: " + " | ".join(errors))
        return

    price, price_date, source = fetched
    if asset.get("priceDate") and price_date <= asset["priceDate"]:
        print(f"Gold source returned older date {price_date}; keeping {asset['priceDate']}")
        return

    asset["price"] = round(float(price), 8)
    asset["priceDate"] = price_date
    asset["source"] = source
    data["updatedAt"] = datetime.now(TZ_MADRID).isoformat(timespec="seconds")

    PRICES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Gold updated: {price} EUR ({price_date}) from {source}")


if __name__ == "__main__":
    main()
