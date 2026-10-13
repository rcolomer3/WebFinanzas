#!/usr/bin/env python3
# Isolated network probe: never reads or writes prices.json.

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,es;q=0.8",
    "Cache-Control": "no-cache",
}


def get(url, *, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print(f"{response.status_code} {response.url}")
    response.raise_for_status()
    return response


def text(url):
    return BeautifulSoup(get(url).text, "html.parser").get_text(" ", strip=True)


def parse_number(value):
    value = value.replace("\xa0", "").replace("€", "").strip()
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".") if value.rfind(",") > value.rfind(".") else value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    return float(value)


def parse_english_history(page):
    rows = []
    for date_text, value in re.findall(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})\s+([0-9]+(?:[.,][0-9]+)?)",
        page,
        flags=re.IGNORECASE,
    ):
        try:
            rows.append((datetime.strptime(date_text, "%b %d, %Y").date().isoformat(), parse_number(value)))
        except ValueError:
            pass
    if not rows:
        raise RuntimeError("no English historical rows parsed")
    return max(rows, key=lambda row: row[0])


def first_working(name, urls):
    errors = []
    for url in urls:
        try:
            row = parse_english_history(text(url))
            print(f"{name} OK: {row[0]} {row[1]} via {url}")
            return row, url
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"{name} failed: " + " | ".join(errors))


def yahoo_probe(host):
    response = get(
        f"https://{host}/v8/finance/chart/PPFB.DE",
        params={"interval": "1d", "range": "10d", "events": "history"},
    )
    payload = response.json()
    result = payload["chart"]["result"][0]
    closes = [x for x in result["indicators"]["quote"][0]["close"] if x is not None]
    if not closes:
        raise RuntimeError("no Yahoo closes")
    print(f"Yahoo OK via {host}: latest close {closes[-1]}")
    return closes[-1]


def main():
    fidelity_urls = [
        "https://ca.investing.com/funds/ie00byx5nx33-historical-data",
        "https://za.investing.com/funds/ie00byx5nx33-historical-data",
        "https://ng.investing.com/funds/ie00byx5nx33-historical-data",
        "https://uk.investing.com/funds/ie00byx5nx33-historical-data",
        "https://es.investing.com/funds/ie00byx5nx33-historical-data",
    ]
    gold_urls = [
        "https://ng.investing.com/etfs/ishares-physical-gold-historical-data?cid=1198444",
        "https://za.investing.com/etfs/ishares-physical-gold-historical-data?cid=1198444",
        "https://ca.investing.com/etfs/ishares-physical-gold-historical-data?cid=1198444",
        "https://www.investing.com/etfs/ishares-physical-gold-historical-data?cid=1198444",
    ]

    fidelity, _ = first_working("Fidelity", fidelity_urls)
    gold, _ = first_working("Gold", gold_urls)

    yahoo_ok = False
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        try:
            yahoo_probe(host)
            yahoo_ok = True
            break
        except Exception as exc:
            print(f"Yahoo failed via {host}: {exc}")

    print(f"SUMMARY Fidelity={fidelity} Gold={gold} Yahoo={yahoo_ok}")


if __name__ == "__main__":
    main()
