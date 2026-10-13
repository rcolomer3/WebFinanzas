#!/usr/bin/env python3
# Isolated network probe: never reads or writes prices.json.

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,es;q=0.8,de;q=0.7",
    "Cache-Control": "no-cache",
}


def get(url, *, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print(f"HTTP {response.status_code} {response.url}")
    response.raise_for_status()
    return response


def clean_text(response):
    return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)


def parse_number(value):
    value = value.replace("\xa0", "").replace("€", "").strip()
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".") if value.rfind(",") > value.rfind(".") else value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    return float(value)


def probe(name, fn):
    try:
        result = fn()
        print(f"RESULT {name}: OK {result}")
        return True, result
    except Exception as exc:
        print(f"RESULT {name}: FAIL {type(exc).__name__}: {exc}")
        return False, str(exc)


def probe_fidelity_investing():
    urls = [
        "https://ca.investing.com/funds/ie00byx5nx33-historical-data",
        "https://za.investing.com/funds/ie00byx5nx33-historical-data",
        "https://uk.investing.com/funds/ie00byx5nx33-historical-data",
    ]
    errors = []
    for url in urls:
        try:
            response = get(url)
            page = clean_text(response)
            match = re.search(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})\s+([0-9]+(?:[.,][0-9]+)?)", page, flags=re.I)
            if not match:
                raise RuntimeError("no dated NAV row")
            return match.group(1), parse_number(match.group(2)), url
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(" | ".join(errors))


def probe_fidelity_morningstar():
    url = "https://www.morningstarfunds.ie/ie/funds/snapshot/snapshot.aspx?id=F00001019E"
    response = get(url)
    page = clean_text(response)
    print("MORNINGSTAR_SNIPPET", page[:800])
    match = re.search(r"NAV.*?(\d{1,2}/\d{1,2}/\d{4}).{0,100}?EUR\s*([0-9]+(?:[.,][0-9]+)?)", page, flags=re.I | re.S)
    if not match:
        raise RuntimeError("NAV/date pattern not found")
    return match.group(1), parse_number(match.group(2)), url


def probe_fidelity_ft():
    url = "https://markets.ft.com/data/funds/tearsheet/historical?s=IE00BYX5NX33:EUR"
    response = get(url)
    page = clean_text(response)
    print("FT_SNIPPET", page[:1600])
    patterns = [
        r"(\d{1,2}/\d{1,2}/\d{4})\s+([0-9]+(?:\.[0-9]+)?)",
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})\s+([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            return match.group(1), parse_number(match.group(2)), url
    raise RuntimeError("dated NAV row not found")


def yahoo_chart(symbol, host="query2.finance.yahoo.com"):
    response = get(
        f"https://{host}/v8/finance/chart/{symbol}",
        params={"interval": "1d", "range": "10d", "events": "history"},
    )
    payload = response.json()
    result = payload["chart"]["result"][0]
    points = [(ts, close) for ts, close in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]) if close is not None]
    if not points:
        raise RuntimeError("no Yahoo closes")
    return points[-1]


def probe_fidelity_ariva():
    url = "https://www.ariva.de/fonds/fidelity-msci-world-index-fund-p-acc-eur"
    response = get(url)
    page = clean_text(response)
    print("ARIVA_SNIPPET", page[:1400])
    match = re.search(r"ISIN:\s*IE00BYX5NX33.{0,200}?([0-9]+,[0-9]+)\s*€", page, flags=re.I | re.S)
    if not match:
        raise RuntimeError("fund quote not found")
    return parse_number(match.group(1)), url


def probe_gold_goyax():
    url = "https://www.goyax.de/etcs/IE00B4ND3602/ishares-physical-metals-plc/"
    response = get(url)
    page = clean_text(response)
    match = re.search(r"Xetra\s+([0-9]+(?:[.,][0-9]+)?)\s*EUR\s+(\d{1,2}:\d{2})", page, flags=re.I)
    if not match:
        raise RuntimeError("Xetra row not found")
    return parse_number(match.group(1)), match.group(2), url


def main():
    checks = [
        ("Fidelity Investing", probe_fidelity_investing),
        ("Fidelity Morningstar", probe_fidelity_morningstar),
        ("Fidelity FT Markets", probe_fidelity_ft),
        ("Fidelity Yahoo fund", lambda: yahoo_chart("0P0001CLDK.F")),
        ("Fidelity Yahoo ISIN Stuttgart", lambda: yahoo_chart("IE00BYX5NX33.SG")),
        ("Fidelity Ariva", probe_fidelity_ariva),
        ("Gold Goyax Xetra", probe_gold_goyax),
        ("Gold Yahoo query2", lambda: yahoo_chart("PPFB.DE")),
        ("Gold Yahoo query1", lambda: yahoo_chart("PPFB.DE", "query1.finance.yahoo.com")),
    ]
    results = {}
    for name, fn in checks:
        results[name] = probe(name, fn)[0]
    print("SUMMARY", results)


if __name__ == "__main__":
    main()
