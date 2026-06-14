"""
The autopilot -- turns the morning scan into paper trades, mechanically.

The judgment lives in the scan files: the pre-market task picks the
top 10 and writes numeric entries, stops, and targets; the intraday
reversal-watch task adds per-symbol directives ("exit", "hold
overnight") to the same JSON as the day develops. This module is the
hands, not the head: once a minute, inside the watcher thread, it
checks real quotes against those numbers and records fills in the
practice ledger (market/paper.py). Like everything in Scout, it can
never touch a real account.

House rules:
  enter   High and Medium picks only, between 9:35 and 14:30, the first
          time price confirms through the scan's entry in the pick's
          direction while still within 1.5% of it (no chasing). One shot
          per symbol per day. Calls buy; puts sell short -- treated
          symmetrically (backtests show neither side is reliably better;
          which one works flips with the market regime).
  size    risk $500 (High) / $250 (Medium) of practice money against
          the stop, never more than 15% of the account in one name.
  exit    stop or target hit; a tripwire (2% against the thesis, or a
          giveback of most of the move -- the backtest showed the
          giveback exit lifts the win rate and rescues the short side);
          an "exit" directive from the reversal watch; or the flatten 5
          minutes before the close. A "hold_overnight" directive defers
          the flatten one day -- nothing is held past the second close.
"""

import json
from datetime import datetime
from pathlib import Path

from market import alpaca_options, feed, notify, paper

SCANS_DIR = Path("data/tv_scans")
STATE_PATH = Path("data/autopilot_state.json")
SETTINGS_PATH = Path("data/market_settings.json")   # shared with the watcher

RISK_DOLLARS = {"High": 500.0, "Medium": 250.0}     # Speculative never trades
# NOTE: an earlier build gated puts to High-only after the Jan-Jun 2026
# backtest showed shorts had no edge. The 2024-2025 out-of-sample REVERSED
# that (puts carried the edge, calls were flat), so the asymmetry is a
# regime artifact, not a rule. Calls and puts are now treated symmetrically
# -- the scan's confidence, which reads the current tape, decides.
EXIT_WIRE_CODES = ("move_against", "gave_back")     # tripwires that close a play
MAX_POSITION_FRACTION = 0.15
CHASE_LIMIT = 0.015
# Fallback stop/target when the scan omits them. 1.5% / 3.0% (a clean 2:1)
# is the robust sweet spot from the Jan-Jun 2026 backtest in tools/ --
# higher expectancy than the old 2%/4%, and regime-independent.
DEFAULT_STOP_PCT = 0.015
DEFAULT_TARGET_PCT = 0.03
ENTRY_FROM_MINUTE = 9 * 60 + 35
ENTRY_UNTIL_MINUTE = 14 * 60 + 30
FLATTEN_MINUTES_BEFORE_CLOSE = 5
RESOLVE_RETRY_SECONDS = 900
MAX_LOG = 400


def _read(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def enabled() -> bool:
    return bool(_read(SETTINGS_PATH, {}).get("autopilot", True))


def set_enabled(on: bool):
    _write(SETTINGS_PATH, {**_read(SETTINGS_PATH, {}), "autopilot": bool(on)})


def state() -> dict:
    return _read(STATE_PATH, {"plays": {}, "log": []})


def log_events(day=None) -> list:
    """Decision log, newest first; optionally just one day's."""
    events = state().get("log", [])
    if day:
        events = [e for e in events if e.get("date") == day]
    return list(reversed(events))


def _scan(day: str) -> dict:
    """The day's scan file, or {} if absent / marked as sample data."""
    data = _read(SCANS_DIR / f"{day}.json", {})
    if not isinstance(data, dict) or data.get("sample"):
        return {}
    return data


def _log(st: dict, now, symbol, event, detail):
    st.setdefault("log", []).append({
        "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
        "symbol": symbol, "event": event, "detail": detail,
    })
    del st["log"][:-MAX_LOG]


def _number(value):
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _new_play(pick: dict, today: str) -> dict:
    """One pick -> one play. Validates the scan's numbers and falls back
    to a 1.5% stop / 3% target around the entry when they're unusable."""
    direction = "put" if str(pick.get("direction", "")).lower() == "put" else "call"
    sign = -1 if direction == "put" else 1
    entry = _number(pick.get("entry_price"))
    stop, target = _number(pick.get("stop_price")), _number(pick.get("target_price"))
    if entry:
        # the stop belongs on the losing side, the target on the winning side
        if stop is None or (entry - stop) * sign <= 0:
            stop = entry * (1 - DEFAULT_STOP_PCT * sign)
        if target is None or (target - entry) * sign <= 0:
            target = entry * (1 + DEFAULT_TARGET_PCT * sign)

    play = {
        "day": today, "direction": direction,
        "confidence": pick.get("confidence") or "",
        "entry": entry, "stop": stop, "target": target,
        "status": "watching", "skip_reason": None,
    }
    if entry is None:
        play["status"] = "skipped"
        play["skip_reason"] = "no usable entry price in the scan"
    elif play["confidence"] not in RISK_DOLLARS:
        play["status"] = "skipped"
        play["skip_reason"] = (
            f"{play['confidence'] or 'unrated'} pick — below the confidence bar"
        )
    return play


def prepare(now=None) -> dict:
    """Roll the day forward, adopt new scan picks, and resolve bare
    tickers ("NVDA") to feed symbols ("NASDAQ:NVDA").

    Returns {bare ticker: qualified symbol} so the watcher can quote
    and tripwire the scan picks. Runs even when the autopilot is off --
    the resolution is what makes scan tickers visible to the feed.
    """
    now = now or feed.now_et()
    today = now.strftime("%Y-%m-%d")
    st = state()
    plays = st.setdefault("plays", {})
    changed = False

    # finished plays from earlier days fall away; open positions carry
    for sym in list(plays):
        if plays[sym].get("day") != today and plays[sym].get("status") != "entered":
            del plays[sym]
            changed = True

    for pick in _scan(today).get("watchlist", []):
        sym = str(pick.get("symbol") or "").strip().upper()
        if not sym or sym in plays:
            continue
        play = _new_play(pick, today)
        plays[sym] = play
        changed = True
        if play["status"] == "skipped":
            _log(st, now, sym, "skipped", play["skip_reason"])
        else:
            _log(st, now, sym, "armed",
                 f"{play['confidence']} {play['direction']} · waiting for "
                 f"{play['entry']:,.2f} · stop {play['stop']:,.2f} · "
                 f"target {play['target']:,.2f}")

    # resolve bare tickers; remember failures briefly so one unknown
    # name doesn't cost an HTTP call every minute
    for sym, play in plays.items():
        if play.get("qualified"):
            continue
        if ":" in sym:
            play["qualified"] = sym
            changed = True
            continue
        tried = play.get("resolve_tried")
        if tried:
            try:
                age = (now - datetime.fromisoformat(tried)).total_seconds()
            except ValueError:
                age = RESOLVE_RETRY_SECONDS
            if age < RESOLVE_RETRY_SECONDS:
                continue
        play["resolve_tried"] = now.isoformat(timespec="seconds")
        play["qualified"] = feed.resolve(sym)
        changed = True

    if changed:
        _write(STATE_PATH, st)
    return {s: p["qualified"] for s, p in plays.items() if p.get("qualified")}


def tick(quotes: dict, now=None, phase="open", wire_alerts=()):
    """One decision pass; the watcher calls this right after tripwires."""
    if not enabled():
        return
    now = now or feed.now_et()
    if phase != "open":
        return
    today = now.strftime("%Y-%m-%d")
    minute = now.hour * 60 + now.minute
    close_minute = 13 * 60 if now.date() in feed.HALF_DAYS else 16 * 60
    flattening = minute >= close_minute - FLATTEN_MINUTES_BEFORE_CLOSE
    # Exit on a move against the thesis OR a giveback of most of the move.
    # The Jan-Jun 2026 backtest showed the giveback exit lifts the win rate
    # ~45%->59%, smooths every month, and turns the weak short side from
    # break-even to positive -- well worth the small cap on call upside.
    tripped = {a.get("symbol"): a.get("message", "tripwire")
               for a in wire_alerts if a.get("code") in EXIT_WIRE_CODES}
    directives = _scan(today).get("directives") or {}

    st = state()
    changed = False
    for sym, play in st.get("plays", {}).items():
        quote = quotes.get(play.get("qualified") or "")
        price = (quote or {}).get("close")
        if play["status"] == "entered":
            changed |= _manage(
                st, now, sym, play, price,
                directive=directives.get(sym) or {},
                tripped=tripped.get(sym) or tripped.get(play.get("qualified")),
                flattening=flattening, today=today,
            )
        elif play["status"] == "watching" and play["day"] == today:
            changed |= _hunt(st, now, sym, play, price, minute, quotes)

    if changed:
        _write(STATE_PATH, st)


def _hunt(st, now, sym, play, price, minute, quotes) -> bool:
    """Watch one armed pick for its entry; returns True on a change."""
    if minute > ENTRY_UNTIL_MINUTE:
        play["status"] = "skipped"
        play["skip_reason"] = "never confirmed before the 14:30 entry cutoff"
        _log(st, now, sym, "skipped", play["skip_reason"])
        return True
    if minute < ENTRY_FROM_MINUTE or price is None:
        return False

    sign = -1 if play["direction"] == "put" else 1
    confirmed = (price - play["entry"]) * sign >= 0
    within_reach = abs(price - play["entry"]) <= play["entry"] * CHASE_LIMIT
    if not (confirmed and within_reach):
        return False

    per_share_risk = abs(play["entry"] - play["stop"])
    risk = RISK_DOLLARS[play["confidence"]]
    equity = paper.summary(quotes).get("equity") or paper.STARTING_CASH
    qty = int(min(risk / per_share_risk,
                  equity * MAX_POSITION_FRACTION / price))
    if qty < 1:
        play["status"] = "skipped"
        play["skip_reason"] = "stop too wide to size even one share"
        _log(st, now, sym, "skipped", play["skip_reason"])
        return True

    side = "buy" if play["direction"] == "call" else "sell"
    note = (f"autopilot · {play['confidence']} {play['direction']} pick · "
            f"stop {play['stop']:,.2f} · target {play['target']:,.2f}")
    error = None
    for attempt in (qty, max(1, qty // 2)):
        try:
            paper.trade(play["qualified"], side, attempt, price, note)
            qty, error = attempt, None
            break
        except ValueError as exc:
            error = str(exc)
    if error:
        play["status"] = "skipped"
        play["skip_reason"] = f"couldn't fund it: {error}"
        _log(st, now, sym, "error", play["skip_reason"])
        return True

    play.update(status="entered", qty=qty, fill=price,
                entered_at=now.isoformat(timespec="seconds"))
    verb = "Bought" if side == "buy" else "Shorted"
    detail = (f"{verb} {qty} @ {price:,.2f} · stop {play['stop']:,.2f} · "
              f"target {play['target']:,.2f}")
    _log(st, now, sym, "entered", detail)
    notify.toast(f"Autopilot: {sym}", detail)
    _enter_option(st, now, sym, play)
    return True


def _enter_option(st, now, sym, play):
    """The Alpaca arm: express the same pick as a real option contract
    on the paper options account. Failures never block the stock leg."""
    if not alpaca_options.configured():
        return
    try:
        pick = alpaca_options.pick_contract(
            play.get("qualified") or sym, play["direction"],
            play["entry"], now)
        if pick is None:
            _log(st, now, sym, "option_skipped",
                 f"no {play['direction']} contract fit the "
                 f"${alpaca_options.MAX_PREMIUM:,.0f} premium cap with a "
                 "tradable spread")
            return
        order = alpaca_options.buy(pick["symbol"], pick["qty"], pick["ask"])
        play["option"] = {"symbol": pick["symbol"], "qty": pick["qty"],
                          "limit": pick["ask"], "status": "open",
                          "order_id": order.get("id", "")}
        _log(st, now, sym, "option_entered",
             f"Bought {pick['qty']}x {alpaca_options.describe(pick['symbol'])} "
             f"at {pick['ask']:,.2f} limit · Alpaca paper")
    except Exception as exc:
        _log(st, now, sym, "error", f"options order failed: {exc}")


def _close_option(st, now, sym, play, reason):
    """Unwind the Alpaca leg: cancel any unfilled buy, close the rest."""
    option = play.get("option")
    if not option or option.get("status") != "open":
        return
    alpaca_options.cancel_order(option.get("order_id", ""))
    try:
        alpaca_options.close(option["symbol"])
        option["status"] = "closed"
        _log(st, now, sym, "option_exited",
             f"Closed {alpaca_options.describe(option['symbol'])} at "
             f"market · {reason}")
    except Exception as exc:
        # a 404 here usually means the limit buy never filled -- the
        # cancel above already mopped that up
        option["status"] = "closed"
        _log(st, now, sym, "option_exited",
             f"{alpaca_options.describe(option['symbol'])}: position "
             f"already flat or order never filled ({exc})")


def _manage(st, now, sym, play, price, directive, tripped, flattening,
            today) -> bool:
    """Run one open position's exits; returns True on a change."""
    sign = -1 if play["direction"] == "put" else 1
    reason = None
    if price is not None:
        if (price - play["stop"]) * sign <= 0:
            reason = f"stop {play['stop']:,.2f} hit"
        elif (price - play["target"]) * sign >= 0:
            reason = f"target {play['target']:,.2f} hit"
    if reason is None and directive.get("action") == "exit":
        reason = "reversal watch said exit"
        if directive.get("reason"):
            reason += f": {directive['reason']}"
    if reason is None and tripped:
        reason = f"tripwire: {tripped}"
    if reason is None and flattening:
        if play["day"] != today:
            reason = "second-day close — nothing is held longer"
        elif directive.get("action") != "hold_overnight":
            reason = "end-of-day flatten"
    if reason is None or price is None:
        return False    # nothing to do, or can't price it — next minute

    side = "sell" if play["direction"] == "call" else "buy"
    try:
        paper.trade(play["qualified"], side, play["qty"], price,
                    f"autopilot exit · {reason}")
    except ValueError as exc:
        _log(st, now, sym, "error", f"exit failed: {exc}")
        return True
    pnl = (price - play["fill"]) * play["qty"] * sign
    play.update(status="exited", exit_price=price, exit_reason=reason,
                exited_at=now.isoformat(timespec="seconds"),
                realized=round(pnl, 2))
    verb = "Sold" if side == "sell" else "Covered"
    detail = f"{verb} {play['qty']} @ {price:,.2f} · {pnl:+,.2f} · {reason}"
    _log(st, now, sym, "exited", detail)
    notify.toast(f"Autopilot: {sym} closed", detail)
    _close_option(st, now, sym, play, reason)
    return True
