import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://api.q4.sa/v1/companies"
OUTPUT = "data/companies.json"
API_KEY = os.environ.get("Q4_API_KEY", "").strip()
MIN_SAFE_COMPANIES = 100


def request_page(params):
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "x-api-key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "MizanAlMarafiq/1.0"
        }
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            if error.code == 429 and attempt < 2:
                retry_after = error.headers.get("Retry-After", "3")
                try:
                    wait = min(int(retry_after), 20)
                except ValueError:
                    wait = 3
                print(f"Q4 rate limit. Waiting {wait} seconds.")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Q4 API HTTP {error.code}: {body}") from error
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def load_existing():
    try:
        with open(OUTPUT, encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"companies": []}


def normalize_company(item):
    symbol = str(item.get("symbol", "")).strip()
    if not re.fullmatch(r"\d{4}", symbol):
        return None

    market = str(item.get("market", "")).strip().lower()
    status = str(item.get("status", "active")).strip().lower()

    if market != "main" or status != "active" or item.get("is_etf") is True:
        return None

    name_ar = str(item.get("name_ar") or item.get("name") or "").strip()
    name_en = str(item.get("name_en") or "").strip()

    if not name_ar and not name_en:
        return None

    return {
        "symbol": symbol,
        "name": name_ar or name_en,
        "name_en": name_en,
        "sector": str(item.get("sector") or "unknown").strip(),
        "market": "main",
        "status": "active",
        "isin": item.get("isin"),
        "is_etf": False
    }


def fetch_all_companies():
    params = {
        "market": "main",
        "status": "active",
        "limit": 500
    }
    collected = {}
    page_number = 0

    while True:
        page_number += 1
        if page_number > 10:
            raise RuntimeError("Stopped after 10 pages to prevent an endless pagination loop.")

        payload = request_page(params)
        rows = payload.get("data", [])

        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Q4 response: data is not a list.")

        for item in rows:
            company = normalize_company(item)
            if company:
                collected[company["symbol"]] = company

        pagination = payload.get("pagination") or {}
        cursor = pagination.get("next_cursor")
        if not cursor:
            break

        params["cursor"] = cursor

    companies = sorted(
        collected.values(),
        key=lambda item: int(item["symbol"])
    )

    if len(companies) < MIN_SAFE_COMPANIES:
        raise RuntimeError(
            f"Only {len(companies)} active main-market companies received; "
            f"refusing to replace the existing directory."
        )

    return companies


def main():
    os.makedirs("data", exist_ok=True)
    existing = load_existing()

    if not API_KEY:
        print("WARNING: Q4_API_KEY is not configured.")
        print("Keeping the existing company directory; no files will be overwritten.")
        print(f"Current cached companies: {len(existing.get('companies', []))}")
        return

    try:
        companies = fetch_all_companies()
    except Exception as error:
        print(f"WARNING: Company directory refresh failed: {error}")
        print("Keeping the last known companies.json so market-price updates can continue.")
        return

    document = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "Q4 Companies API (free directory endpoint)",
        "market": "main",
        "count": len(companies),
        "companies": companies
    }

    temporary_path = OUTPUT + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, OUTPUT)

    print(f"Updated main-market company directory: {len(companies)} companies")


if __name__ == "__main__":
    main()
