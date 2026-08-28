"""
Lidl.nl price scraper — designed to run inside GitHub Actions (which has
normal internet access, unlike a sandboxed dev environment).

Reads shopping_list.json, looks each product up on lidl.nl, writes the
results to data.json (read by index.html for the dashboard).

Also dumps a screenshot + raw HTML per product into debug/ on every run,
uploaded as a workflow artifact — so if a product isn't found, we can open
the debug files and fix the matching logic without guessing blind.
"""

import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://www.lidl.nl/q/search?q={query}"
DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(exist_ok=True)

PRICE_RE = re.compile(r"€\s?\d{1,3}[.,]\d{2}")


def extract_prices_near_query(html: str, query: str):
    """
    Generic fallback: find all €-formatted prices in the rendered page and
    return them in document order. Lidl's exact CSS class names change
    often, so instead of hardcoding selectors we scan for the currency
    pattern directly. The first price found is treated as the top search
    result's current price; if two prices appear close together it usually
    means there's a deal (current + crossed-out original).
    """
    matches = PRICE_RE.findall(html)
    return matches


def get_product_info(page, query, qty):
    url = SEARCH_URL.format(query=query)
    page.goto(url, timeout=30000)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(2)  # extra buffer for late price hydration

    html = page.content()

    # Save debug artifacts every run (cheap, and saves a round trip if a
    # product ever stops matching)
    safe_name = re.sub(r"[^a-z0-9]+", "_", query.lower())
    page.screenshot(path=str(DEBUG_DIR / f"{safe_name}.png"), full_page=True)
    (DEBUG_DIR / f"{safe_name}.html").write_text(html, encoding="utf-8")

    prices = extract_prices_near_query(html, query)

    if not prices:
        return {
            "query": query,
            "title": query,
            "price": None,
            "old_price": None,
            "on_deal": False,
            "qty": qty,
            "found": False,
        }

    current = prices[0]
    old = prices[1] if len(prices) > 1 else None

    return {
        "query": query,
        "title": query,
        "price": current,
        "old_price": old,
        "on_deal": old is not None,
        "qty": qty,
        "found": True,
    }


def parse_price(price_str):
    if not price_str:
        return None
    cleaned = price_str.replace("€", "").replace(",", ".").strip()
    cleaned = "".join(c for c in cleaned if c.isdigit() or c == ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def main():
    shopping_list = json.loads(Path("shopping_list.json").read_text())
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="nl-NL", viewport={"width": 1280, "height": 1600})

        for item in shopping_list:
            info = get_product_info(page, item["name"], item["qty"])
            info["unit_price"] = parse_price(info["price"])
            info["subtotal"] = (info["unit_price"] or 0) * info["qty"]
            results.append(info)

        browser.close()

    total = sum(r["subtotal"] for r in results)

    output = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "items": results,
        "total": round(total, 2),
    }

    Path("public").mkdir(exist_ok=True)
    Path("public/data.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
