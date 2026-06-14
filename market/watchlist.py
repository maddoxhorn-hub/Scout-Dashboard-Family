"""
One combined watchlist.

Two sources, same shape:
  scan    today's top-10 file written by the pre-market scan task
          (data/tv_scans/YYYY-MM-DD.json) -- present on Maddox's PC,
          simply absent everywhere else
  manual  tickers anyone adds by hand on the Markets page
          (data/manual_watchlist.json)

Every item: {symbol, direction, entry_price, source, ...extras}.
direction is call/up (needs the stock to rise) or put/down.
"""

import json
from datetime import datetime
from pathlib import Path

SCANS_DIR = Path("data/tv_scans")
MANUAL_PATH = Path("data/manual_watchlist.json")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


# Scan files should hold exchange-qualified symbols ("NASDAQ:NVDA"), but
# a bare "NVDA" gets quietly qualified here -- one lookup per symbol per
# server run -- instead of silently never getting a quote.
_QUALIFY_CACHE = {}


def _qualify(symbol: str) -> str:
    if ":" in symbol:
        return symbol
    if symbol not in _QUALIFY_CACHE:
        from market import feed

        _QUALIFY_CACHE[symbol] = feed.resolve(symbol) or symbol
    return _QUALIFY_CACHE[symbol]


def scan_items(day=None) -> list:
    day = day or datetime.now().strftime("%Y-%m-%d")
    data = _read_json(SCANS_DIR / f"{day}.json") or {}
    if data.get("sample"):
        return []   # demo data for the Scans page -- never watch or trade it
    items = []
    for raw in data.get("watchlist", []):
        if not raw.get("symbol"):
            continue
        items.append({
            "symbol": _qualify(raw["symbol"]),
            "direction": raw.get("direction", "up"),
            "entry_price": raw.get("entry_price"),
            "thesis": raw.get("thesis", ""),
            "confidence": raw.get("confidence", ""),
            "source": "scan",
        })
    return items


def manual_items() -> list:
    items = _read_json(MANUAL_PATH) or []
    for item in items:
        item["source"] = "manual"
    return items


def all_items() -> list:
    """Scan picks first, then manual adds; first occurrence of a symbol wins."""
    seen, merged = set(), []
    for item in scan_items() + manual_items():
        if item["symbol"] in seen:
            continue
        seen.add(item["symbol"])
        merged.append(item)
    return merged


def add(symbol: str, direction: str, entry_price):
    items = _read_json(MANUAL_PATH) or []
    items = [i for i in items if i.get("symbol") != symbol]
    items.append({
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def remove(symbol: str):
    items = _read_json(MANUAL_PATH) or []
    items = [i for i in items if i.get("symbol") != symbol]
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def scan_days() -> list:
    """Dates that have a saved scan report, newest first."""
    if not SCANS_DIR.exists():
        return []
    return sorted(
        (p.stem for p in SCANS_DIR.glob("????-??-??.md")), reverse=True
    )
