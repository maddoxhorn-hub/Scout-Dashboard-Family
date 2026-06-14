"""
Live quotes from TradingView's public screener feed, plus the NYSE clock.

These are the same numbers that power tradingview.com's screener pages:
one POST, no login, no key. Good enough for watching and paper trading;
never the basis for a real order.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

SCAN_URL = "https://scanner.tradingview.com/america/scan"

# Column order here defines the keys of every quote dict this module
# returns. "change" is % vs yesterday's close; "change_from_open" is %
# vs today's open; VWAP and RSI are TradingView's intraday values.
COLUMNS = [
    "description", "close", "change", "change_from_open", "VWAP", "RSI",
    "volume", "average_volume_10d_calc", "high", "low", "premarket_change",
]


def quotes(symbols, timeout=10) -> dict:
    """{symbol: quote dict} for exchange-qualified symbols ("NYSE:F").

    Symbols TradingView doesn't recognize are absent from the result;
    a network failure returns {} so callers keep their last known state.
    """
    symbols = sorted({s for s in symbols if s})
    if not symbols:
        return {}
    payload = {"symbols": {"tickers": symbols}, "columns": COLUMNS}
    try:
        resp = requests.post(SCAN_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json().get("data") or []
    except Exception:
        return {}
    out = {}
    for row in rows:
        fields = dict(zip(COLUMNS, row.get("d", [])))
        if fields.get("close") is None:
            continue
        out[row["s"]] = fields
    return out


_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")


def resolve(ticker: str):
    """'aapl' -> 'NASDAQ:AAPL', or None if no US exchange knows it.

    Already-qualified names ("NYSE:F") pass through if they're real.
    """
    ticker = (ticker or "").strip().upper().replace(" ", "")
    if not ticker:
        return None
    if ":" in ticker:
        return ticker if ticker in quotes([ticker]) else None
    candidates = [f"{ex}:{ticker}" for ex in _EXCHANGES]
    found = quotes(candidates)
    for sym in candidates:  # prefer the major listing, not dict order
        if sym in found:
            return sym
    return None


# ----------------------------------------------------------------------
# The NYSE clock (everything below is Eastern time)
# ----------------------------------------------------------------------

ET = ZoneInfo("America/New_York")

# Update when 2027 ends; until then market_phase degrades to a plain
# weekday check for unknown years.
HOLIDAYS = {
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15),
    date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25),
    date(2027, 12, 24),
}

HALF_DAYS = {          # 1:00 PM close
    date(2026, 11, 27), date(2026, 12, 24),
    date(2027, 11, 26),
}


def now_et() -> datetime:
    return datetime.now(ET)


def market_phase(at=None) -> str:
    """'open' | 'premarket' | 'afterhours' | 'closed'."""
    at = at or now_et()
    day = at.date()
    if at.weekday() >= 5 or day in HOLIDAYS:
        return "closed"
    minute = at.hour * 60 + at.minute
    close = 13 * 60 if day in HALF_DAYS else 16 * 60
    if 4 * 60 <= minute < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= minute < close:
        return "open"
    if close <= minute < 20 * 60:
        return "afterhours"
    return "closed"


PHASE_LABEL = {
    "open": "Market open",
    "premarket": "Pre-market",
    "afterhours": "After hours",
    "closed": "Market closed",
}
