"""
The market watcher.

One daemon thread inside the app server (started from app.py, same
pattern as the bank-downloads watcher). Once a minute while the market
is open it pulls quotes for every watched ticker and paper position,
runs the tripwires, and raises alerts three ways:

  1. a desktop notification, instantly and for free
  2. a row in the alert feed on the Markets page
  3. optionally, a short Claude run that reads the news and judges
     whether the wire-trip is a genuine reversal or noise -- only on
     machines with the Claude Code CLI installed and the toggle on

Off hours it naps and keeps the last state on screen. All state lives
in two JSON files under data/, so a server restart re-fires nothing.
"""

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from market import autopilot, feed, notify, paper, tripwires, watchlist

STATE_PATH = Path("data/market_state.json")
ALERTS_PATH = Path("data/market_alerts.json")
SETTINGS_PATH = Path("data/market_settings.json")

POLL_SECONDS = 60
IDLE_SECONDS = 300
MAX_ALERTS_KEPT = 500
MAX_HISTORY_POINTS = 500


# ----------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------

def _read(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def latest() -> dict:
    """The watcher's last snapshot: quotes, history, phase, timestamp."""
    return _read(STATE_PATH, {})


def alerts(limit=200) -> list:
    """Alert feed, newest first."""
    return list(reversed(_read(ALERTS_PATH, [])))[:limit]


def settings() -> dict:
    return {"claude_judge": False, **_read(SETTINGS_PATH, {})}


def save_settings(**changes):
    _write(SETTINGS_PATH, {**settings(), **changes})


def change_signal() -> tuple:
    """Cheap tuple that changes when quotes, alerts, or trades change --
    the Markets page polls this to refresh itself."""
    def mtime(path):
        try:
            return int(path.stat().st_mtime)
        except OSError:
            return 0
    return (mtime(STATE_PATH), mtime(ALERTS_PATH), paper.change_signal())


def _append_alerts(new_alerts: list):
    log = _read(ALERTS_PATH, [])
    log.extend(new_alerts)
    _write(ALERTS_PATH, log[-MAX_ALERTS_KEPT:])


# ----------------------------------------------------------------------
# The optional Claude judge
# ----------------------------------------------------------------------

def _claude_cli():
    """The claude CLI's path. Its installer puts it in ~/.local/bin,
    which isn't always on the PATH the server inherits."""
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / (
        "claude.exe" if sys.platform == "win32" else "claude")
    return str(local) if local.exists() else None


def claude_available() -> bool:
    return _claude_cli() is not None


def _judge_in_background(symbol, direction, messages, today):
    """Ask the local Claude CLI for a 2-3 sentence read on a tripped
    ticker. Runs in its own thread; one judgment per ticker per day."""
    cli = _claude_cli()
    if not cli:
        return

    plain = symbol.split(":")[-1]
    prompt = (
        f"A stock-watching tripwire fired for {plain} "
        f"(the working thesis was that it would go "
        f"{'up' if tripwires.direction_sign(direction) > 0 else 'down'} today). "
        f"Signals: {'; '.join(messages)}. "
        "Search the web once or twice for fresh news on this ticker from today. "
        "Then answer in 2-3 plain-English sentences: does this look like a "
        "genuine reversal or just noise, and why? End with 'Confidence: "
        "High/Medium/Low'. Do not give buy/sell instructions."
    )

    def run():
        try:
            result = subprocess.run(
                [cli, "-p", prompt, "--allowedTools", "WebSearch"],
                capture_output=True, text=True, timeout=300,
                stdin=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if sys.platform == "win32" else 0),
            )
            verdict = (result.stdout or "").strip()
            if not verdict:
                return
            verdict = verdict[:600]
            _append_alerts([{
                "date": today,
                "time": feed.now_et().strftime("%H:%M"),
                "symbol": symbol,
                "code": "claude",
                "message": verdict,
            }])
            notify.toast(f"Claude on {plain}", verdict)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name=f"judge-{plain}").start()


# ----------------------------------------------------------------------
# One polling pass
# ----------------------------------------------------------------------

def poll_once() -> list:
    """Pull quotes, run tripwires, persist state. Returns new alerts."""
    now = feed.now_et()
    today = now.strftime("%Y-%m-%d")
    phase = feed.market_phase(now)

    items = watchlist.all_items()
    # scan files hold bare tickers ("NVDA") but the feed only answers
    # exchange-qualified ones ("NASDAQ:NVDA") -- the autopilot resolves
    # and remembers the mapping for everyone
    qualified = autopilot.prepare(now)

    def _feed_symbol(sym):
        return sym if ":" in sym else qualified.get(sym)

    symbols = {_feed_symbol(i["symbol"]) for i in items}
    symbols |= {p["symbol"] for p in paper.positions()}
    symbols |= set(qualified.values())
    symbols.discard(None)

    state = latest()
    quotes = feed.quotes(symbols) if symbols else {}
    if quotes:
        state["quotes"] = {**state.get("quotes", {}), **quotes}
    state["phase"] = phase
    state["updated_at"] = now.isoformat(timespec="seconds")

    # intraday price history for the page's sparklines (today only)
    if state.get("history_date") != today:
        state["history_date"] = today
        state["history"] = {}
    if phase in ("premarket", "open", "afterhours"):
        history = state.setdefault("history", {})
        stamp = now.strftime("%H:%M")
        for sym, quote in quotes.items():
            points = history.setdefault(sym, [])
            points.append([stamp, quote["close"]])
            del points[:-MAX_HISTORY_POINTS]

    # tripwires only fire while the market is actually trading
    new_alerts = []
    if phase == "open":
        wires = state.setdefault("wires", {})
        judge_on = settings().get("claude_judge") and claude_available()
        for item in items:
            quote = quotes.get(_feed_symbol(item["symbol"]))
            if not quote:
                continue
            slot = wires.setdefault(item["symbol"], {})
            hits = tripwires.evaluate(item, quote, slot, today)
            if not hits:
                continue
            stamp = now.strftime("%H:%M")
            for hit in hits:
                new_alerts.append({**hit, "date": today, "time": stamp})
            plain = item["symbol"].split(":")[-1]
            notify.toast(
                f"Scout: {plain} tripwire",
                "; ".join(h["message"] for h in hits),
            )
            if judge_on and slot.get("judged") != today:
                slot["judged"] = today
                _judge_in_background(
                    item["symbol"], item.get("direction", "up"),
                    [h["message"] for h in hits], today,
                )

    try:
        autopilot.tick(quotes, now, phase, new_alerts)
    except Exception:
        pass    # the autopilot must never take the watcher down

    _write(STATE_PATH, state)
    if new_alerts:
        _append_alerts(new_alerts)
    return new_alerts


def watch_forever():
    while True:
        try:
            poll_once()
        except Exception:
            pass
        nap = POLL_SECONDS if feed.market_phase() != "closed" else IDLE_SECONDS
        time.sleep(nap)
