"""
Paper trading -- practice money, real prices, zero risk.

A single SQLite file (data/paper.db) holds a trade log; cash and
positions are replayed from it on demand, so the log is the only truth.
Selling more than you own simply takes the position negative (a short)
-- the arithmetic is identical, the UI explains it.

Like everything in Scout, this never touches a real account.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

STARTING_CASH = float(getattr(config, "PAPER_STARTING_CASH", 100_000.00))
_DB = Path(getattr(config, "PAPER_DB", "data/paper.db"))


def _connect():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            qty REAL NOT NULL,
            price REAL NOT NULL,
            note TEXT
        )"""
    )
    return con


def trade(symbol: str, side: str, qty: float, price: float, note=""):
    """Record a paper fill. Buys must be affordable; that's the only rule."""
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise ValueError("Shares and price must both be positive.")
    if side == "buy":
        available = cash()
        if qty * price > available + 0.01:
            raise ValueError(
                f"That costs ${qty * price:,.2f} but the account has "
                f"${available:,.2f} of practice cash."
            )
    with _connect() as con:
        con.execute(
            "INSERT INTO trades (ts, symbol, side, qty, price, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"),
             symbol, side, qty, price, note),
        )


def _rows():
    with _connect() as con:
        return con.execute(
            "SELECT ts, symbol, side, qty, price FROM trades ORDER BY id"
        ).fetchall()


def cash() -> float:
    value = STARTING_CASH
    for _, _, side, qty, price in _rows():
        value += -qty * price if side == "buy" else qty * price
    return value


def positions() -> list:
    """[{symbol, qty, avg_cost}] -- qty < 0 is a short position.

    Average cost follows the usual convention: it moves when a position
    grows (weighted in), and holds steady when the position shrinks.
    """
    book = {}
    for _, symbol, side, qty, price in _rows():
        signed = qty if side == "buy" else -qty
        held, avg = book.get(symbol, (0.0, 0.0))
        new_held = held + signed
        if held == 0 or (held > 0) == (signed > 0):      # opening / growing
            avg = (abs(held) * avg + abs(signed) * price) / abs(new_held) \
                if new_held else 0.0
        elif (held > 0) != (new_held > 0) and new_held != 0:  # flipped sides
            avg = price
        book[symbol] = (new_held, avg)
    return [
        {"symbol": s, "qty": q, "avg_cost": a}
        for s, (q, a) in sorted(book.items()) if abs(q) > 1e-9
    ]


def summary(prices: dict) -> dict:
    """Account snapshot. prices = {symbol: {"close":..., "change":...}}."""
    held_value = day_pnl = 0.0
    priced = True
    for pos in positions():
        quote = prices.get(pos["symbol"]) or {}
        close = quote.get("close")
        if close is None:
            priced = False
            continue
        held_value += pos["qty"] * close
        change = quote.get("change")
        if change is not None and change > -100:
            prior = close / (1 + change / 100)
            day_pnl += pos["qty"] * (close - prior)
    cash_now = cash()
    equity = cash_now + held_value
    return {
        "cash": cash_now,
        "held_value": held_value,
        "equity": equity,
        "total_pnl": equity - STARTING_CASH,
        "day_pnl": day_pnl,
        "fully_priced": priced,
    }


def trades_frame() -> pd.DataFrame:
    with _connect() as con:
        return pd.read_sql_query(
            "SELECT ts AS time, symbol, side, qty AS shares, price, note "
            "FROM trades ORDER BY id DESC", con
        )


def reset():
    """Wipe the practice account back to its starting cash."""
    with _connect() as con:
        con.execute("DELETE FROM trades")


def change_signal() -> tuple:
    try:
        stat = _DB.stat()
        return (stat.st_size, int(stat.st_mtime))
    except OSError:
        return (0, 0)
