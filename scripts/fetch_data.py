import concurrent.futures
import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request

LEGACY_STOCKS = [
    ("2222", "أرامكو السعودية"),
    ("1120", "مصرف الراجحي"),
    ("1180", "البنك الأهلي السعودي"),
    ("1150", "مصرف الإنماء"),
    ("1211", "معادن"),
    ("2083", "مرافق"),
    ("4143", "تالكو"),
    ("4017", "فقيه الطبية"),
    ("2285", "المطاحن العربية"),
    ("2310", "سبكيم العالمية"),
    ("4190", "جرير"),
    ("8210", "بوبا العربية"),
    ("8010", "التعاونية"),
    ("2370", "مسك"),
    ("4260", "بدجت السعودية"),
    ("4031", "الخدمات الأرضية"),
    ("2280", "المراعي"),
    ("7010", "stc"),
    ("2380", "بترو رابغ"),
    ("4001", "أسواق العثيم"),
]

TASI = "^TASI.SR"
OUTPUT = "data/market.json"
COMPANIES_FILE = "data/companies.json"


def load_companies():
    try:
        with open(COMPANIES_FILE, encoding="utf-8") as file:
            document = json.load(file)

        rows = document.get("companies", [])
        companies = []

        for item in rows:
            symbol = str(item.get("symbol", "")).strip()
            name = str(item.get("name") or item.get("name_en") or "").strip()

            if (
                re.fullmatch(r"\d{4}", symbol)
                and name
                and item.get("market", "main") == "main"
                and item.get("status", "active") == "active"
                and item.get("is_etf") is not True
            ):
                companies.append((symbol, name))

        if companies:
            unique = {symbol: name for symbol, name in companies}
            result = sorted(unique.items(), key=lambda item: int(item[0]))
            print(
                f"Using company directory: {len(result)} companies "
                f"(source: {document.get('source', 'local cache')})"
            )
            return result
    except (FileNotFoundError, json.JSONDecodeError, AttributeError) as error:
        print(f"WARNING: Could not read {COMPANIES_FILE}: {error}")

    print("WARNING: Falling back to the original 20-stock list.")
    return LEGACY_STOCKS


def get_quote(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol, safe="")
        + "?range=5d&interval=1d"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    results = data.get("chart", {}).get("result")
    if not results:
        raise Exception("No market data")

    result = results[0]
    meta = result.get("meta", {})
    quote = result.get("indicators", {}).get("quote", [{}])[0]

    closes = [x for x in quote.get("close", []) if x is not None]
    volumes = [x for x in quote.get("volume", []) if x is not None]

    price = meta.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]

    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    if previous is None and len(closes) > 1:
        previous = closes[-2]

    if price is None:
        raise Exception("Price unavailable")

    change = price - previous if previous else None
    change_pct = change / previous * 100 if previous else None
    timestamps = result.get("timestamp", [])

    return {
        "price": round(float(price), 4),
        "previous": round(float(previous), 4) if previous else None,
        "change": round(float(change), 4) if change is not None else None,
        "changePct": round(float(change_pct), 4) if change_pct is not None else None,
        "volume": int(volumes[-1]) if volumes else None,
        "timestamp": int(timestamps[-1]) if timestamps else int(time.time()),
        "stale": False,
        "error": None
    }


def fetch_stock(stock, old_data):
    symbol, name = stock

    try:
        data = get_quote(symbol + ".SR")
    except Exception as error:
        old = old_data.get(symbol, {})
        data = {
            "price": old.get("price"),
            "previous": old.get("previous"),
            "change": old.get("change"),
            "changePct": old.get("changePct"),
            "volume": old.get("volume"),
            "timestamp": old.get("timestamp"),
            "stale": old.get("price") is not None,
            "error": str(error)[:200]
        }

    data["symbol"] = symbol
    data["name"] = name
    return data


def main():
    os.makedirs("data", exist_ok=True)

    try:
        with open(OUTPUT, encoding="utf-8") as file:
            old_doc = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        old_doc = {}

    old_data = {
        item["symbol"]: item
        for item in old_doc.get("stocks", [])
        if item.get("symbol")
    }

    companies = load_companies()

    # Yahoo Finance is queried in small batches to reduce rate-limit risk.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        stocks = list(
            executor.map(
                lambda item: fetch_stock(item, old_data),
                companies
            )
        )

    try:
        tasi = get_quote(TASI)
        tasi["symbol"] = TASI
    except Exception as error:
        tasi = old_doc.get("tasi") or {"price": None}
        tasi["stale"] = tasi.get("price") is not None
        tasi["error"] = str(error)[:200]

    company_doc = {}
    try:
        with open(COMPANIES_FILE, encoding="utf-8") as file:
            company_doc = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    document = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "Yahoo Finance",
        "companies_source": company_doc.get("source", "Legacy fallback list"),
        "companies_updated_at": company_doc.get("updated_at"),
        "companies_count": len(companies),
        "tasi": tasi,
        "stocks": stocks
    }

    temporary_path = OUTPUT + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, OUTPUT)

    available = sum(
        1 for stock in stocks
        if stock["price"] is not None and not stock["stale"]
    )
    print(f"Updated {available}/{len(stocks)} stock quotes.")
    print(f"Company directory size: {len(companies)}")


if __name__ == "__main__":
    main()
