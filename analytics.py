"""
All the math, no network calls.

Takes the raw sheet rows and turns them into: headline P&L stats, an
equity curve with drawdown, losing-streak counts, inferred open positions,
and the R-multiple comparison against the Phase 5 backtest profile.
"""

from datetime import date

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Column matching -- tolerant of small header differences
# ----------------------------------------------------------------------

def _norm(name: str) -> str:
    return str(name).lower().replace(" ", "").replace("&", "").replace("_", "")


def _find_col(df: pd.DataFrame, *candidates):
    """Return the actual column name matching any candidate, else None."""
    lookup = {_norm(c): c for c in df.columns}
    for cand in candidates:
        hit = lookup.get(_norm(cand))
        if hit is not None:
            return hit
    return None


# ----------------------------------------------------------------------
# Cleaning
# ----------------------------------------------------------------------

def prepare_trades(raw: pd.DataFrame) -> pd.DataFrame:
    """Add typed helper columns: timestamp, pnl (numeric), status, closed.

    Rows the bot logs as OPEN carry the literal string "OPEN" in the P&L
    column; pd.to_numeric turns those into NaN, so `closed` simply means
    "this row has a realized P&L number".
    """
    if raw is None or raw.empty:
        # Dtypes matter even with zero rows: "closed" must be bool so
        # trades[trades["closed"]] masks rows instead of selecting columns.
        return pd.DataFrame(
            {
                "timestamp": pd.Series(dtype="datetime64[ns]"),
                "pnl": pd.Series(dtype="float64"),
                "status": pd.Series(dtype="object"),
                "closed": pd.Series(dtype="bool"),
            }
        )

    df = raw.copy()
    ts_col = _find_col(df, "Timestamp", "Time", "Date")
    pnl_col = _find_col(df, "P&L", "PnL", "PL", "Profit")
    status_col = _find_col(df, "Status")

    df["timestamp"] = (
        pd.to_datetime(df[ts_col], errors="coerce") if ts_col else pd.NaT
    )
    df["pnl"] = (
        pd.to_numeric(df[pnl_col], errors="coerce") if pnl_col else np.nan
    )
    df["status"] = (
        df[status_col].astype(str).str.strip().str.upper() if status_col else ""
    )
    df["closed"] = df["pnl"].notna()
    return df


def closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades[trades["closed"]].copy()
    return out.sort_values("timestamp")


# ----------------------------------------------------------------------
# Headline stats
# ----------------------------------------------------------------------

def headline_stats(trades: pd.DataFrame) -> dict:
    closed = closed_trades(trades)
    n = len(closed)
    if n == 0:
        return {"n_closed": 0}

    pnl = closed["pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    today_mask = closed["timestamp"].dt.date == date.today()
    gross_win = wins.sum()
    gross_loss = abs(losses.sum())

    return {
        "n_closed": n,
        "total_pnl": pnl.sum(),
        "today_pnl": pnl[today_mask].sum(),
        "win_rate": len(wins) / n,
        "n_wins": len(wins),
        "avg_win": wins.mean() if len(wins) else 0.0,
        "avg_loss": losses.mean() if len(losses) else 0.0,
        "expectancy": pnl.mean(),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "best": pnl.max(),
        "worst": pnl.min(),
    }


# ----------------------------------------------------------------------
# Equity curve + drawdown
# ----------------------------------------------------------------------

def equity_curve(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    """Equity after each closed trade, anchored at starting capital."""
    closed = closed_trades(trades).dropna(subset=["timestamp"])
    if closed.empty:
        return pd.DataFrame(columns=["timestamp", "equity", "peak", "drawdown"])

    curve = pd.DataFrame(
        {
            "timestamp": closed["timestamp"].values,
            "equity": starting_capital + closed["pnl"].cumsum().values,
        }
    )
    anchor = pd.DataFrame(
        {
            "timestamp": [closed["timestamp"].iloc[0] - pd.Timedelta(days=1)],
            "equity": [starting_capital],
        }
    )
    curve = pd.concat([anchor, curve], ignore_index=True)
    curve["peak"] = curve["equity"].cummax()
    curve["drawdown"] = curve["equity"] - curve["peak"]
    return curve


# ----------------------------------------------------------------------
# Streaks
# ----------------------------------------------------------------------

def streaks(trades: pd.DataFrame) -> dict:
    closed = closed_trades(trades)
    max_losing = 0
    run = 0
    for value in closed["pnl"]:
        if value < 0:
            run += 1
            max_losing = max(max_losing, run)
        else:
            run = 0

    current_len = 0
    current_kind = "none"
    for value in reversed(list(closed["pnl"])):
        kind = "losing" if value < 0 else "winning" if value > 0 else "flat"
        if current_len == 0:
            current_kind = kind
            current_len = 1
        elif kind == current_kind:
            current_len += 1
        else:
            break

    return {
        "max_losing": max_losing,
        "current_len": current_len,
        "current_kind": current_kind,
    }


# ----------------------------------------------------------------------
# Open positions (inferred from the log)
# ----------------------------------------------------------------------

def open_positions(trades: pd.DataFrame) -> pd.DataFrame:
    """Pair *_to_open rows against *_to_close rows on (ticker, type,
    strike, expiry) and return whatever is still open.

    This is an inference from the log, not a broker statement -- if it
    ever disagrees with Alpaca, trust Alpaca and tighten the log.
    """
    df = trades
    action_col = _find_col(df, "Action")
    ticker_col = _find_col(df, "Ticker", "Symbol")
    if not action_col or not ticker_col or df.empty:
        return pd.DataFrame()

    qty_col = _find_col(df, "Qty", "Quantity")
    type_col = _find_col(df, "Type")
    strike_col = _find_col(df, "Strike")
    expiry_col = _find_col(df, "Expiry", "Expiration")
    premium_col = _find_col(df, "Premium Paid", "Premium")

    book = {}
    for _, row in df.sort_values("timestamp").iterrows():
        key = (
            row.get(ticker_col),
            row.get(type_col) if type_col else "",
            row.get(strike_col) if strike_col else "",
            row.get(expiry_col) if expiry_col else "",
        )
        action = str(row.get(action_col, "")).lower()
        try:
            qty = abs(float(row.get(qty_col, 1) or 1)) if qty_col else 1.0
        except (TypeError, ValueError):
            qty = 1.0

        if "open" in action:
            entry = book.setdefault(key, {"qty": 0.0, "row": row})
            entry["qty"] += qty
            entry["row"] = row
        elif "close" in action and key in book:
            book[key]["qty"] -= qty

    rows = []
    for key, entry in book.items():
        if entry["qty"] > 0.0001:
            row = entry["row"]
            rows.append(
                {
                    "Ticker": key[0],
                    "Type": key[1],
                    "Strike": key[2],
                    "Expiry": key[3],
                    "Qty open": entry["qty"],
                    "Opened": row.get("timestamp"),
                    "Premium": row.get(premium_col) if premium_col else None,
                }
            )
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# Backtest vs. live (everything in R)
# ----------------------------------------------------------------------

def r_report(trades: pd.DataFrame, r_dollars: float, backtest: dict) -> dict:
    """Compare realized results, expressed in R, against the locked
    Phase 5 profile."""
    closed = closed_trades(trades).dropna(subset=["timestamp"])
    n = len(closed)
    if n == 0 or r_dollars <= 0:
        return {"n_closed": n}

    r = closed["pnl"] / r_dollars
    wins_r = r[r > 0]
    losses_r = r[r < 0]

    first_ts = closed["timestamp"].iloc[0]
    years = max((pd.Timestamp.now() - first_ts).days, 1) / 365.25
    expected_to_date = backtest["expected_annual_r"] * years

    cum = pd.DataFrame(
        {"timestamp": closed["timestamp"].values, "cum_r": r.cumsum().values}
    )

    line_dates = pd.date_range(first_ts.normalize(), pd.Timestamp.now(), freq="D")
    expected_line = pd.DataFrame(
        {
            "timestamp": line_dates,
            "expected_r": [
                backtest["expected_annual_r"] * (d - first_ts).days / 365.25
                for d in line_dates
            ],
        }
    )

    return {
        "n_closed": n,
        "cum_r": r.sum(),
        "expected_to_date": expected_to_date,
        "years": years,
        "win_rate": (r > 0).mean(),
        "avg_winner_r": wins_r.mean() if len(wins_r) else 0.0,
        "avg_loser_r": losses_r.mean() if len(losses_r) else 0.0,
        "cum_series": cum,
        "expected_series": expected_line,
    }
