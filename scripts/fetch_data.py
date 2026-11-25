
import concurrent.futures
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

STOCKS = [
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

    closes = [
        x for x in quote.get("close", [])
        if x is not None
    ]

    volumes = [
        x for x in quote.get("volume", [])
        if x is not None
    ]

    price = meta.get("regularMarketPrice")

    if price is None and closes:
        price = closes[-1]

    previous = (
        meta.get("chartPreviousClose")
        or meta.get("previousClose")
    )

    if previous is None and len(closes) > 1:
        previous = closes[-2]

    if price is None:
        raise Exception("Price unavailable")

    change = price - previous if previous else None

    change_pct = (
        change / previous * 100
        if previous else None
    )

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
        x["symbol"]: x
        for x in old_doc.get("stocks", [])
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        stocks = list(
            executor.map(
                lambda item: fetch_stock(item, old_data),
                STOCKS
            )
        )

    try:
        tasi = get_quote(TASI)
        tasi["symbol"] = TASI
    except Exception as error:
        tasi = old_doc.get("tasi") or {"price": None}
        tasi["stale"] = tasi.get("price") is not None
        tasi["error"] = str(error)[:200]

    document = {
        "updated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "source": "Yahoo Finance",
        "tasi": tasi,
        "stocks": stocks
    }

    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(
            document,
            file,
            ensure_ascii=False,
            indent=2
        )

    available = sum(
        1 for stock in stocks
        if stock["price"] is not None and not stock["stale"]
    )

    print(f"Updated {available}/{len(stocks)} stocks")


if __name__ == "__main__":
    main()
