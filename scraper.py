"""Collect verified Lidl Netherlands offers from Lidl's public leaflet API."""
from __future__ import annotations

import argparse, html, json, re, unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

FOLDERS_URL = "https://www.lidl.nl/c/service-contact-folders/s10008124"
FLYER_API = "https://endpoints.leaflets.schwarz/v4/flyer"
USER_AGENT = "Lidly/2.0 (+personal Lidl offer dashboard)"
DEFAULT_STORE = {"name": "Lidl Meppel", "city": "Meppel"}
LEAFLET_RE = re.compile(r'href=["\']([^"\']*/l/folders/([^/]+)/ar/(\d+)[^"\']*)', re.I)


def fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def discover_leaflets(page_html: str, base_url: str = FOLDERS_URL) -> list[dict[str, str]]:
    """Return official weekly/Weekenddeal leaflet identifiers found on Lidl's page."""
    found: dict[str, dict[str, str]] = {}
    for href, slug, region in LEAFLET_RE.findall(html.unescape(page_html)):
        normalized = slug.casefold()
        if "hah-" not in normalized:
            continue
        found[slug] = {"identifier": slug, "region": region, "url": urljoin(base_url, href),
                       "kind": "weekenddeals" if "weekenddeal" in normalized else "weekly"}
    return list(found.values())


def flyer_endpoint(identifier: str, region: str = "0") -> str:
    return f"{FLYER_API}?{urlencode({'flyer_identifier': identifier, 'region_id': region})}"


def parse_money(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return None
    return round(number, 2) if number >= 0 else None


def _trusted_lidl_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host == "lidl.nl" or host.endswith(".lidl.nl")


def parse_flyer(payload: dict[str, Any], source: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate an API payload and extract only complete structured products."""
    if payload.get("success") is not True or not isinstance(payload.get("flyer"), dict):
        raise ValueError("Lidl leaflet API returned no successful flyer")
    flyer = payload["flyer"]
    raw_products = flyer.get("products") or {}
    values = raw_products.values() if isinstance(raw_products, dict) else raw_products
    valid_from = flyer.get("offerStartDate") or flyer.get("startDate")
    valid_until = flyer.get("offerEndDate") or flyer.get("endDate")
    source_url = flyer.get("flyerUrlAbsolute") or source["url"]
    offers = []
    for product in values:
        if not isinstance(product, dict):
            continue
        title = html.unescape(str(product.get("title") or "")).strip()
        price = parse_money(product.get("price"))
        image, product_url = str(product.get("image") or "").strip(), str(product.get("url") or "").strip()
        if not title or price is None or not image.startswith("https://") or not _trusted_lidl_url(product_url):
            continue
        offers.append({"id": str(product.get("productId") or product_url), "name": title,
                       "brand": html.unescape(str(product.get("brand") or "")).strip() or None,
                       "price": price, "old_price": None, "discount": None,
                       "valid_from": valid_from, "valid_until": valid_until, "image": image,
                       "source_url": product_url, "leaflet_url": source_url,
                       "source_type": source["kind"], "verified": True})
    meta = {"name": flyer.get("name"), "title": flyer.get("title"), "kind": source["kind"],
            "valid_from": valid_from, "valid_until": valid_until, "url": source_url, "products": len(offers)}
    return meta, offers


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value))


def match_score(item: dict[str, Any], offer: dict[str, Any]) -> float:
    names = [item.get("name", ""), *(item.get("aliases") or [])]
    target = normalize(f"{offer.get('brand') or ''} {offer['name']}")
    best = 0.0
    for candidate in filter(None, map(normalize, names)):
        candidate_tokens, target_tokens = set(candidate.split()), set(target.split())
        containment = len(candidate_tokens & target_tokens) / max(len(candidate_tokens), 1)
        substring = 1.0 if candidate in target else 0.0
        best = max(best, .55 * containment + .30 * substring + .15 * SequenceMatcher(None, candidate, target).ratio())
    return round(best, 4)


def match_shopping_list(items: list[dict[str, Any]], offers: list[dict[str, Any]], threshold: float = .68) -> list[dict[str, Any]]:
    matches = []
    for item in items:
        ranked = sorted(((match_score(item, offer), offer) for offer in offers), key=lambda pair: pair[0], reverse=True)
        score, offer = ranked[0] if ranked else (0.0, None)
        matches.append({**item, "matched": bool(offer and score >= threshold), "match_score": score,
                        "deal": offer if offer and score >= threshold else None})
    return matches


def is_current_leaflet(meta: dict[str, Any], today) -> bool:
    """Exclude preview/future folders and expired folders from the active dashboard."""
    try:
        start = datetime.fromisoformat(meta["valid_from"]).date()
        end = datetime.fromisoformat(meta["valid_until"]).date()
    except (KeyError, TypeError, ValueError):
        return False
    return start <= today <= end


def update_history(path: Path, offers: list[dict[str, Any]], captured_at: str) -> list[dict[str, Any]]:
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(history, list): history = []
    except (FileNotFoundError, json.JSONDecodeError): history = []
    known = {(row.get("captured_at"), row.get("id"), row.get("price")) for row in history if isinstance(row, dict)}
    for offer in offers:
        row = {"captured_at": captured_at, "id": offer["id"], "name": offer["name"],
               "price": offer["price"], "source_url": offer["source_url"]}
        if (row["captured_at"], row["id"], row["price"]) not in known: history.append(row)
    history = history[-5000:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return history


def collect() -> dict[str, Any]:
    now = datetime.now(timezone.utc).astimezone()
    captured_at = now.isoformat(timespec="seconds")
    errors, leaflets_meta, offers_by_key = [], [], {}
    try:
        sources = discover_leaflets(fetch_text(FOLDERS_URL))
        if not sources: raise ValueError("Geen actuele week- of Weekenddeals-folders gevonden")
    except Exception as exc:
        sources, errors = [], [f"Folderoverzicht: {exc}"]
    for source in sources:
        try:
            payload = json.loads(fetch_text(flyer_endpoint(source["identifier"], source["region"])))
            meta, offers = parse_flyer(payload, source)
            if not is_current_leaflet(meta, now.date()):
                continue
            leaflets_meta.append(meta)
            for offer in offers: offers_by_key[(offer["id"], offer["price"], offer["valid_until"])] = offer
        except Exception as exc: errors.append(f"{source['identifier']}: {exc}")
    offers = sorted(offers_by_key.values(), key=lambda row: (row["source_type"], row["name"]))
    shopping = json.loads(Path("shopping_list.json").read_text(encoding="utf-8"))
    matched = match_shopping_list(shopping, offers)
    return {"schema_version": 2, "generated_at": captured_at, "status": "ok" if offers else "error",
            "error": "; ".join(errors) if errors else None, "store": DEFAULT_STORE,
            "source": {"name": "Lidl Nederland", "folders_url": FOLDERS_URL, "leaflets": leaflets_meta},
            "offers": offers, "shopping_list": matched,
            "summary": {"verified_offers": len(offers), "shopping_matches": sum(1 for row in matched if row["matched"]), "leaflets": len(leaflets_meta)}}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default="public/data.json"); parser.add_argument("--history", default="public/price_history.json")
    args = parser.parse_args(); result = collect(); output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_history(Path(args.history), result["offers"], result["generated_at"][:10])
    print(json.dumps(result["summary"], ensure_ascii=False))
    if result["status"] != "ok": print(result["error"]); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
