"""
Alpaca paper options -- the autopilot's second arm.

The stock ledger (market/paper.py) measures whether the scan's picks
point the right way. This module measures the part a stock proxy can't:
what the same decisions earn when expressed as real option contracts,
with real chains, spreads, and time decay. It talks only to Alpaca's
PAPER endpoint -- save_keys refuses anything else -- so by construction
it can never touch a real account.

Contract choice mirrors Maddox's real constraints: 7-18 days to expiry,
calls for call picks / puts for put picks, the strike nearest the
scan's entry that fits inside the ~$300 premium cap with a sane spread.
If no contract fits the cap, the pick is skipped here (and the skip is
the finding: the cap forces lottery strikes on expensive names).
"""

import json
from datetime import timedelta
from pathlib import Path

import requests

PAPER_HOST = "https://paper-api.alpaca.markets"
DATA_HOST = "https://data.alpaca.markets"
KEYS_PATH = Path("data/alpaca_options.json")     # data/ is gitignored

MAX_PREMIUM = 300.0          # per position, like the real account
MAX_CONTRACTS = 3
EXPIRY_MIN_DAYS = 7          # 7+ DTE preferred...
EXPIRY_MAX_DAYS = 18         # ...but within the under-2-day holding style
STRIKE_WINDOW = 0.20         # only look at strikes within 20% of entry
TIMEOUT = 12


# ----------------------------------------------------------------------
# Keys
# ----------------------------------------------------------------------

def _keys() -> dict:
    try:
        return json.loads(KEYS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def configured() -> bool:
    keys = _keys()
    return bool(keys.get("key") and keys.get("secret"))


def save_keys(key: str, secret: str):
    """Validate against the PAPER endpoint and save. Returns an error
    string for the page to show, or None on success."""
    key, secret = (key or "").strip(), (secret or "").strip()
    if not key or not secret:
        return "Both the Key and the Secret are needed."
    if not key.startswith("PK"):
        return ("That doesn't look like a paper-trading key (they start "
                "with PK). Live keys are refused on purpose.")
    try:
        resp = requests.get(
            f"{PAPER_HOST}/v2/account",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return f"Couldn't reach Alpaca: {exc}"
    if resp.status_code in (401, 403):
        return ("Alpaca rejected the pair. Copy both values right after "
                "clicking Regenerate — the Secret is only shown once.")
    if not resp.ok:
        return f"Alpaca answered {resp.status_code}: {resp.text[:120]}"
    account = resp.json()
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps({
        "key": key, "secret": secret,
        "account_number": account.get("account_number", ""),
    }), encoding="utf-8")
    level = int(account.get("options_approved_level") or 0)
    if level < 2:
        return ("Saved, but this paper account's options level is "
                f"{level} — it needs level 2 to buy calls and puts. "
                "Check the account's options settings on Alpaca.")
    return None


def forget_keys():
    try:
        KEYS_PATH.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------
# REST plumbing
# ----------------------------------------------------------------------

def _headers() -> dict:
    keys = _keys()
    return {"APCA-API-KEY-ID": keys.get("key", ""),
            "APCA-API-SECRET-KEY": keys.get("secret", "")}


def _get(host, path, params=None):
    resp = requests.get(f"{host}{path}", headers=_headers(),
                        params=params or {}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def account() -> dict:
    """{"equity", "day_pnl", "level"} or {} if unreachable."""
    if not configured():
        return {}
    try:
        raw = _get(PAPER_HOST, "/v2/account")
        equity = float(raw.get("equity") or 0)
        last = float(raw.get("last_equity") or equity)
        return {"equity": equity, "day_pnl": equity - last,
                "level": int(raw.get("options_approved_level") or 0)}
    except (requests.RequestException, ValueError):
        return {}


def open_positions() -> list:
    """[{symbol, qty, avg_cost, value, unrealized}] for option holdings."""
    if not configured():
        return []
    try:
        raw = _get(PAPER_HOST, "/v2/positions")
    except requests.RequestException:
        return []
    out = []
    for pos in raw:
        if pos.get("asset_class") != "us_option":
            continue
        out.append({
            "symbol": pos.get("symbol", ""),
            "qty": float(pos.get("qty") or 0),
            "avg_cost": float(pos.get("avg_entry_price") or 0),
            "value": float(pos.get("market_value") or 0),
            "unrealized": float(pos.get("unrealized_pl") or 0),
        })
    return out


# ----------------------------------------------------------------------
# Contract selection
# ----------------------------------------------------------------------

def describe(occ: str) -> str:
    """'NVDA260626C00180000' -> 'NVDA $180 call exp 06/26'."""
    try:
        tail = occ[-15:]
        date, kind, strike = tail[:6], tail[6], int(tail[7:]) / 1000
        under = occ[:-15]
        word = "call" if kind == "C" else "put"
        price = f"{strike:g}"
        return f"{under} ${price} {word} exp {date[2:4]}/{date[4:6]}"
    except (ValueError, IndexError):
        return occ


def pick_contract(underlying: str, direction: str, entry_price: float, now):
    """The strike nearest the entry that fits the premium cap with a
    sane spread, 7-18 days out. Returns {"symbol","ask","bid","qty"}
    or None if nothing qualifies (which is itself a finding)."""
    underlying = underlying.split(":")[-1].upper()
    kind = "put" if str(direction).lower() == "put" else "call"
    params = {
        "feed": "indicative",
        "type": kind,
        "expiration_date_gte": (now + timedelta(days=EXPIRY_MIN_DAYS)).strftime("%Y-%m-%d"),
        "expiration_date_lte": (now + timedelta(days=EXPIRY_MAX_DAYS)).strftime("%Y-%m-%d"),
        "strike_price_gte": round(entry_price * (1 - STRIKE_WINDOW), 2),
        "strike_price_lte": round(entry_price * (1 + STRIKE_WINDOW), 2),
        "limit": 500,
    }
    snapshots = _get(DATA_HOST, f"/v1beta1/options/snapshots/{underlying}",
                     params).get("snapshots") or {}

    candidates = []
    for occ, snap in snapshots.items():
        quote = snap.get("latestQuote") or {}
        bid, ask = quote.get("bp") or 0, quote.get("ap") or 0
        if bid <= 0 or ask <= 0 or ask * 100 > MAX_PREMIUM:
            continue
        mid = (bid + ask) / 2
        if (ask - bid) > max(0.20, 0.35 * mid):
            continue        # spread too wide to trade honestly
        try:
            strike = int(occ[-8:]) / 1000
        except ValueError:
            continue
        candidates.append({"symbol": occ, "ask": ask, "bid": bid,
                           "strike": strike,
                           "distance": abs(strike - entry_price)})
    if not candidates:
        return None
    best = min(candidates, key=lambda c: c["distance"])
    best["qty"] = max(1, min(MAX_CONTRACTS, int(MAX_PREMIUM // (best["ask"] * 100))))
    return best


# ----------------------------------------------------------------------
# Orders
# ----------------------------------------------------------------------

def buy(occ: str, qty: int, limit_price: float):
    """Limit-buy at the ask. Returns the order dict, or raises."""
    resp = requests.post(
        f"{PAPER_HOST}/v2/orders", headers=_headers(), timeout=TIMEOUT,
        json={"symbol": occ, "qty": str(int(qty)), "side": "buy",
              "type": "limit", "limit_price": str(round(limit_price, 2)),
              "time_in_force": "day"},
    )
    resp.raise_for_status()
    return resp.json()


def close(occ: str):
    """Close the whole position at market. Returns the order dict."""
    resp = requests.delete(f"{PAPER_HOST}/v2/positions/{occ}",
                           headers=_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def cancel_order(order_id: str):
    """Cancel a pending order; quietly fine if it already filled/expired."""
    if not order_id:
        return
    try:
        requests.delete(f"{PAPER_HOST}/v2/orders/{order_id}",
                        headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException:
        pass


def order_status(order_id: str) -> dict:
    try:
        return _get(PAPER_HOST, f"/v2/orders/{order_id}")
    except requests.RequestException:
        return {}
