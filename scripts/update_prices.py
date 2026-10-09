#!/usr/bin/env python3

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
TZ_XETRA = ZoneInfo("Europe/Berlin")

HEADERS = {
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9,es;q=0.8",
}


def request(url, *, params=None, timeout=20):
    last_error = None
    for _ in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Request failed for {url}: {last_error}")


def page_text(url):
    return BeautifulSoup(request(url).text, "html.parser").get_text(" ", strip=True)


def parse_number(value):
    value = value.strip().replace("\xa0", "").replace("€", "").replace("%", "")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    return float(value)


def load_prices():
    return json.loads(PRICES_FILE.read_text(encoding="utf-8"))


def save_prices(data):
    PRICES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def apply_asset(data, key, *, price, price_date, source):
    asset = data["assets"][key]
    old_date = asset.get("priceDate")
    if old_date and price_date < old_date:
        print(f"{key}: source returned an older date; keeping existing value")
        return False
    if not (0 < float(price) < 1_000_000):
        raise ValueError(f"{key}: invalid price {price}")
    asset["price"] = round(float(price), 8)
    asset["priceDate"] = price_date
    asset["source"] = source
    return True


def fetch_bitcoin():
    payload = request(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": "bitcoin",
            "vs_currencies": "eur",
            "include_24hr_change": "true",
        },
    ).json()
    price = float(payload["bitcoin"]["eur"])
    change = payload["bitcoin"].get("eur_24h_change")
    date = datetime.now(TZ_MADRID).date().isoformat()
    return price, date, "CoinGecko", change


def parse_investing_nav(text):
    candidates = []

    for date_text, value in re.findall(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2},\s+\d{4})\s+([0-9]+(?:\.[0-9]+)?)",
        text,
    ):
        try:
            candidates.append((datetime.strptime(date_text, "%b %d, %Y").date(), parse_number(value)))
        except ValueError:
            pass

    for date_text, value in re.findall(
        r"(\d{2}\.\d{2}\.\d{4})\s+([0-9]+(?:,[0-9]+)?)",
        text,
    ):
        try:
            candidates.append((datetime.strptime(date_text, "%d.%m.%Y").date(), parse_number(value)))
        except ValueError:
            pass

    if not candidates:
        raise RuntimeError("No NAV rows found")

    date, price = max(candidates, key=lambda item: item[0])
    return price, date.isoformat()


def fetch_fidelity():
    urls = [
        "https://uk.investing.com/funds/ie00byx5nx33-historical-data",
        "https://es.investing.com/funds/ie00byx5nx33-historical-data",
        "https://it.investing.com/funds/ie00byx5nx33-historical-data",
    ]
    errors = []
    for url in urls:
        try:
            price, date = parse_investing_nav(page_text(url))
            return price, date, "Investing.com - NAV"
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(" | ".join(errors))


MONTHS_EN = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
MONTHS_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def parse_vanguard_official(text):
    candidates = []

    section = text.split("Historical Prices", 1)[-1]
    if "Distribution history" in section:
        section = section.split("Distribution history", 1)[0]
    for date_text, value in re.findall(
        rf"(\d{{1,2}}\s+(?:{MONTHS_EN})\s+\d{{4}})\s+€?\s*([0-9]+(?:[.,][0-9]+)?)",
        section,
    ):
        try:
            candidates.append((datetime.strptime(date_text, "%d %b %Y").date(), parse_number(value)))
        except ValueError:
            pass

    section = text.split("Precios históricos", 1)[-1]
    if "Historial de distribución" in section:
        section = section.split("Historial de distribución", 1)[0]
    for day, month, year, value in re.findall(
        r"(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sept|sep|oct|nov|dic)\.?\s+(\d{4})\s+([0-9]+(?:[.,][0-9]+)?)\s*€",
        section,
        flags=re.IGNORECASE,
    ):
        date = datetime(int(year), MONTHS_ES[month.lower()], int(day)).date()
        candidates.append((date, parse_number(value)))

    if not candidates:
        raise RuntimeError("No official Vanguard NAV rows found")

    date, price = max(candidates, key=lambda item: item[0])
    return price, date.isoformat()


def fetch_vanguard():
    official_urls = [
        "https://www.nl.vanguard/professional/product/fund/equity/9229/emerging-markets-stock-index-fund-eur-acc",
        "https://www.es.vanguard/profesionales/producto/fondo/renta-variable/9229/emerging-markets-stock-index-fund-eur-acc",
    ]
    errors = []
    for url in official_urls:
        try:
            price, date = parse_vanguard_official(page_text(url))
            return price, date, "Vanguard - NAV"
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    try:
        price, date = parse_investing_nav(
            page_text("https://uk.investing.com/funds/vanguard-em-stock-inst-eur-acc-historical-data")
        )
        return price, date, "Investing.com - NAV"
    except Exception as exc:
        errors.append(f"Investing fallback: {exc}")

    raise RuntimeError(" | ".join(errors))


def parse_marketscreener_gold(text):
    candidates = []
    pattern = r"(\d{2}/\d{2}/(?:\d{2}|\d{4}))\s+([0-9]+(?:[.,][0-9]+)?)\s*(?:€|EUR)"
    for date_text, value in re.findall(pattern, text):
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                date = datetime.strptime(date_text, fmt).date()
                candidates.append((date, parse_number(value)))
                break
            except ValueError:
                pass

    if not candidates:
        raise RuntimeError("No Xetra PPFB quote rows found on MarketScreener")

    date, price = max(candidates, key=lambda item: item[0])
    return price, date.isoformat()


def fetch_gold_yahoo():
    payload = request(
        "https://query1.finance.yahoo.com/v8/finance/chart/PPFB.DE",
        params={"interval": "1d", "range": "10d", "events": "history"},
    ).json()
    result = payload["chart"]["result"][0]
    points = [
        (ts, close)
        for ts, close in zip(result["timestamp"], result["indicators"]["quote"][0]["close"])
        if close is not None
    ]
    if not points:
        raise RuntimeError("Yahoo Finance returned no PPFB.DE closes")
    timestamp, price = points[-1]
    # Yahoo daily timestamps may be anchored at session open; use exchange-local date.
    date = datetime.fromtimestamp(timestamp, TZ_XETRA).date().isoformat()
    change = None
    if len(points) >= 2 and points[-2][1]:
        change = (float(price) / float(points[-2][1]) - 1.0) * 100.0
    return float(price), date, "Yahoo Finance - Xetra (PPFB.DE)", change


def fetch_gold_xetra():
    # Prefer the structured Xetra EUR time series over scraping unstructured pages.
    errors = []
    try:
        return fetch_gold_yahoo()
    except Exception as exc:
        errors.append(f"Yahoo primary: {exc}")
    urls = [
        "https://es.marketscreener.com/cotizacion/etf/ISHARES-PHYSICAL-GOLD-ETC-124881157/cotizaciones/",
        "https://www.marketscreener.com/quote/etf/ISHARES-PHYSICAL-GOLD-ETC-124881157/quotes/",
    ]
    for url in urls:
        try:
            price, date = parse_marketscreener_gold(page_text(url))
            return price, date, "MarketScreener - Xetra"
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(" | ".join(errors))


def main():
    data = load_prices()
    results = {}
    fetchers = {
        "BTC": fetch_bitcoin,
        "IE00BYX5NX33": fetch_fidelity,
        "IE0031786696": fetch_vanguard,
        "IE00B4ND3602": fetch_gold_xetra,
    }

    for key, fetcher in fetchers.items():
        try:
            fetched = fetcher()
            price, price_date, source = fetched[:3]
            changed = apply_asset(data, key, price=price, price_date=price_date, source=source)
            results[key] = {
                "status": "updated" if changed else "kept",
                "price": data["assets"][key]["price"],
                "priceDate": data["assets"][key]["priceDate"],
                "source": data["assets"][key]["source"],
            }
            if len(fetched) > 3 and fetched[3] is not None:
                results[key]["dailyChangePct"] = round(float(fetched[3]), 4)
        except Exception as exc:
            existing = data["assets"][key]
            results[key] = {
                "status": "kept_after_error",
                "price": existing["price"],
                "priceDate": existing["priceDate"],
                "source": existing["source"],
                "error": str(exc),
            }

    # updatedAt indicates the run, not that every asset has a fresh quote.
    data["updatedAt"] = datetime.now(TZ_MADRID).isoformat(timespec="seconds")
    failed = [key for key, result in results.items() if result["status"] == "kept_after_error"]
    if failed:
        print("WARNING: prices not refreshed for: " + ", ".join(failed))
    save_prices(data)
    print(json.dumps({"updatedAt": data["updatedAt"], "assets": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
