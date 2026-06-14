"""Scans -- the daily premarket scan: top-10 watchlist + intraday checks.

Reads the files the scheduled scan drops into data/tv_scans/ — one
YYYY-MM-DD.json per trading day, with a matching .md written report.
Pure local file reads; nothing here calls a market API.
"""

import json
from datetime import date, datetime
from pathlib import Path

import streamlit as st

import ui
from market import alpaca_options, autopilot, feed, paper, watcher

SCAN_DIR = Path(__file__).resolve().parent.parent / "data" / "tv_scans"
BACKTEST_DIR = Path(__file__).resolve().parent.parent / "data" / "backtests"

_DIRECTION_COLORS = {"call": "green", "put": "red"}
_CONFIDENCE_COLORS = {"High": "green", "Medium": "orange", "Speculative": "gray"}


def _scan_dates() -> list:
    """Days that have a scan file, oldest first."""
    if not SCAN_DIR.exists():
        return []
    days = []
    for path in SCAN_DIR.glob("*.json"):
        try:
            days.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(days)


@st.cache_data(ttl=60, show_spinner=False)
def _load_scan(day_iso: str) -> dict:
    return json.loads((SCAN_DIR / f"{day_iso}.json").read_text(encoding="utf-8"))


def _latest_prices(check_log):
    """Last seen price per symbol across the day's checks, plus the
    time of the last check that carried prices."""
    prices, as_of = {}, None
    for check in check_log:
        snap = check.get("prices") or {}
        for symbol, price in snap.items():
            if isinstance(price, (int, float)):
                prices[symbol] = price
        if snap:
            as_of = check.get("time")
    return prices, as_of


def _fmt_clock(ts) -> str:
    """'2026-06-15T08:45:00-04:00' -> '8:45 AM'; falls back to the raw text."""
    try:
        return datetime.fromisoformat(ts).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return str(ts) if ts else "—"


@st.cache_data(ttl=60, show_spinner=False)
def _options_snapshot():
    return alpaca_options.account(), alpaca_options.open_positions()


def _alpaca_strip():
    """The options arm: account cards when connected, the key form when not."""
    if not alpaca_options.configured():
        with st.expander("Connect the Alpaca options account"):
            st.caption(
                "This lets the autopilot also buy real option contracts on "
                "your Alpaca PAPER account — practice money, real chains and "
                "spreads. On alpaca.markets: Profile → Manage Accounts → the "
                "Claude Options Account → Regenerate, then copy BOTH values "
                "right away (the Secret is shown only once)."
            )
            key = st.text_input("API Key", key="alpaca_key")
            secret = st.text_input("API Secret", type="password",
                                   key="alpaca_secret")
            if st.button("Save and test", key="alpaca_save", type="primary"):
                error = alpaca_options.save_keys(key, secret)
                if error is None:
                    st.success("Connected — option contracts trade from the "
                               "next entry on.")
                    _options_snapshot.clear()
                    st.rerun()
                elif error.startswith("Saved"):
                    st.warning(error)
                else:
                    st.error(error)
        return

    acct, holdings = _options_snapshot()
    if not acct:
        st.caption("Alpaca options account: connected, but unreachable "
                   "right now — orders retry on their own.")
        return
    held = " · ".join(alpaca_options.describe(p["symbol"]) for p in holdings)
    unrealized = sum(p["unrealized"] for p in holdings)
    ui.cards([
        ui.card("Options account", ui.money(acct["equity"]),
                note=f"Alpaca paper · options level {acct['level']}"),
        ui.card("Options day P&L", ui.money(acct["day_pnl"], signed=True),
                tone=ui.tone_of(round(acct["day_pnl"], 2)),
                note="includes closed trades"),
        ui.card("Option contracts held", str(len(holdings)),
                note=held if held else "none right now"),
        ui.card("Unrealized on contracts", ui.money(unrealized, signed=True),
                tone=ui.tone_of(round(unrealized, 2)),
                note="open positions only"),
    ])


def _autopilot_panel(day_iso: str):
    """Status, kill switch, and decision log for the paper autopilot."""
    ui.section("Autopilot",
               "Trades the morning scan with practice money — the scan "
               "supplies the judgment, the watcher enforces it every minute")
    on = autopilot.enabled()
    chosen = st.toggle(
        "Autopilot is live (practice account only)",
        value=on, key="autopilot_toggle",
        help="High picks risk $500, Medium $250, Speculative never trade. "
             "Entries confirm through the scan's price without chasing; "
             "exits are the stop, the target, a reversal alert, or the "
             "end-of-day flatten. It cannot touch a real account.",
    )
    if chosen != on:
        autopilot.set_enabled(chosen)
        st.toast("Autopilot is " + ("on" if chosen else "off"),
                 icon="🤖" if chosen else "💤")

    quotes = watcher.latest().get("quotes", {})
    summ = paper.summary(quotes)
    plays = autopilot.state().get("plays", {})
    open_plays = {s: p for s, p in plays.items() if p.get("status") == "entered"}
    realized = sum(p.get("realized", 0) for p in plays.values()
                   if p.get("status") == "exited")
    open_pnl = 0.0
    for play in open_plays.values():
        close = (quotes.get(play.get("qualified") or "") or {}).get("close")
        if close is not None:
            sign = -1 if play["direction"] == "put" else 1
            open_pnl += (close - play["fill"]) * play["qty"] * sign

    ui.cards([
        ui.card("Autopilot", "On" if chosen else "Off",
                note="practice money only", dim=not chosen),
        ui.card("Open positions", str(len(open_plays)),
                note=" · ".join(s.split(":")[-1] for s in open_plays)
                if open_plays else "none right now"),
        ui.card("Open P&L", ui.money(open_pnl, signed=True),
                tone=ui.tone_of(round(open_pnl, 2)),
                note="on autopilot positions"),
        ui.card("Realized today", ui.money(realized, signed=True),
                tone=ui.tone_of(round(realized, 2)),
                note=f"account {ui.money(summ['equity'])}"),
    ])

    _alpaca_strip()

    events = autopilot.log_events(day_iso)
    if events:
        ui.timeline([
            (e.get("time", "—"),
             f'{str(e.get("symbol", "?")).split(":")[-1]} — {e.get("detail", "")}',
             ["The autopilot hit a problem here"] if e.get("event") == "error"
             else [])
            for e in events[:40]
        ])
    else:
        st.caption(
            "No autopilot decisions on this day. It arms itself each "
            "trading morning when the scan lands."
        )

    _backtest_panel()


def _backtest_panel():
    """Show the most recent strategy backtest, if one has been run."""
    if not BACKTEST_DIR.exists():
        return
    files = list(BACKTEST_DIR.glob("*.json"))
    if not files:
        return
    # show the most representative run -- the one with the most setups
    # (a multi-year out-of-sample beats a single rosy quarter)
    data = None
    for path in files:
        try:
            d = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if data is None or d.get("n_candidates", 0) > data.get("n_candidates", 0):
            data = d
    if data is None:
        return
    rows = sorted(data.get("results", []),
                  key=lambda r: r.get("expectancy_R", 0), reverse=True)[:8]
    if not rows:
        return

    with st.expander("Strategy backtest — how these rules did on history"):
        st.caption(
            f"{data.get('n_candidates', 0)} setups · "
            f"{data.get('start', '')} → {data.get('end', '')} · "
            f"{len(data.get('universe', []))} liquid names · real intraday "
            "prices. Measures the **stock** move + entry/stop/target rules, "
            "not option premium (theta/IV) — that's what the live options "
            "account measures. A marginal edge across regimes; read as "
            "directional context, not a promise."
        )
        st.dataframe(
            [{
                "gap ≥": f"{r['gap_min']}%",
                "stop": f"{r['stop_pct']}%",
                "target": f"{r['target_pct']}%",
                "trades": r["trades"],
                "win": f"{r['win_rate']*100:.0f}%",
                "exp. R": round(r["expectancy_R"], 3),
                "profit factor": round(r["profit_factor"], 2),
                "call R": round(r.get("call_exp", 0), 2),
                "put R": round(r.get("put_exp", 0), 2),
            } for r in rows],
            hide_index=True, width="stretch",
        )
        st.caption("Sorted by expectancy (R per trade). 'call R' vs 'put R' "
                   "shows which side carries the edge.")


def render():
    days = _scan_dates()
    if not days:
        ui.section("Daily scans",
                   "Top-10 premarket watchlist + reversal checks every 30 minutes")
        st.info(
            "No scans yet — the first one lands automatically on the next "
            "trading morning before the bell, nothing to set up. Each day "
            "gets a top-10 watchlist here, then updates through the close."
        )
        _autopilot_panel(feed.now_et().strftime("%Y-%m-%d"))
        return

    head_l, head_r = st.columns([5, 1.4], vertical_alignment="bottom")
    with head_l:
        ui.section("Daily scans",
                   "Top-10 premarket watchlist + reversal checks every 30 minutes")
    with head_r:
        picked = st.date_input(
            "Scan date", value=days[-1], min_value=days[0], max_value=days[-1],
            key="scan_date",
        )

    if picked not in days:
        st.info(
            f"No scan for {picked:%A, %B %d} — markets were closed or the "
            "scan didn't run that day. Pick another date."
        )
        return

    try:
        data = _load_scan(picked.isoformat())
    except (OSError, json.JSONDecodeError):
        st.error(
            f"The scan file for {picked:%B %d} couldn't be read. If the "
            "morning scan is mid-write, try Refresh in a minute."
        )
        return

    if data.get("sample"):
        st.info(
            "This is sample data so you can see the page — the first real "
            "scan replaces it automatically on the next trading morning."
        )

    watchlist = data.get("watchlist") or []
    check_log = data.get("check_log") or []
    prices, as_of = _latest_prices(check_log)

    # --- the day at a glance ------------------------------------------------
    n_calls = sum(1 for w in watchlist if (w.get("direction") or "").lower() == "call")
    n_high = sum(1 for w in watchlist if w.get("confidence") == "High")
    n_alerts = sum(len(c.get("alerts") or []) for c in check_log)
    status = str(data.get("market_status") or "—").replace("_", " ").title()
    ui.cards([
        ui.card("Watchlist", str(len(watchlist)),
                note=f"{n_calls} calls · {len(watchlist) - n_calls} puts"),
        ui.card("High confidence", str(n_high),
                note=f"of {len(watchlist)} picks"),
        ui.card("Checks so far", str(len(check_log)),
                note=f"Last at {as_of}" if as_of
                else "First check lands after the open",
                dim=not check_log),
        ui.card("Market", status,
                note=f"Scanned at {_fmt_clock(data.get('generated_at'))}"),
    ])

    _autopilot_panel(picked.isoformat())

    # --- watchlist ------------------------------------------------------------
    ui.section(
        "Watchlist",
        "Since-entry move is green when price is going the pick's way "
        "(up for calls, down for puts)"
        + (f" · prices as of {as_of}" if as_of else ""),
    )
    cards = []
    for w in watchlist:
        symbol = w.get("symbol", "?")    # may be exchange-qualified
        ticker = str(symbol).split(":")[-1]
        direction = (w.get("direction") or "").lower()
        confidence = w.get("confidence")
        entry = w.get("entry_price")
        pm_change = w.get("premarket_change_pct")

        badges = [ui.pill(direction.upper() or "?",
                          _DIRECTION_COLORS.get(direction, "gray"))]
        if confidence:
            badges.append(ui.pill(confidence,
                                  _CONFIDENCE_COLORS.get(confidence, "gray")))

        latest = prices.get(symbol)
        move = None
        move_tone = "neutral"
        if latest is not None and entry:
            change_pct = (latest - entry) / entry * 100
            move = f"{change_pct:+.1f}%"
            favored = -change_pct if direction == "put" else change_pct
            move_tone = ui.tone_of(round(favored, 2))

        bits = [f"Entry {ui.money(entry)}"]
        if latest is not None:
            bits.append(f"last {ui.money(latest)}")
        if pm_change is not None:
            bits.append(f"{pm_change:+.1f}% premarket")
        stop, target = w.get("stop_price"), w.get("target_price")
        if isinstance(stop, (int, float)):
            bits.append(f"stop {ui.money(stop)}")
        if isinstance(target, (int, float)):
            bits.append(f"target {ui.money(target)}")
        price_line = " · ".join(bits)

        triggers = w.get("reversal_triggers")
        if isinstance(triggers, list):
            triggers = " · ".join(str(t) for t in triggers)

        cards.append(ui.watch_card(
            ticker, badges, price_line, w.get("thesis") or "",
            triggers=f"Reversal triggers: {triggers}" if triggers else None,
            move=move, move_tone=move_tone,
        ))
    if cards:
        ui.watch_grid(cards)
    else:
        st.caption("The watchlist for this day is empty.")

    # --- intraday check log -----------------------------------------------------
    ui.section("Intraday checks",
               "Newest first — orange dots mark reversal alerts")
    if not check_log:
        st.caption("No checks logged yet. They start after the opening bell.")
    else:
        ui.timeline([
            (c.get("time", "—"), c.get("summary", ""),
             [str(a) for a in (c.get("alerts") or [])])
            for c in reversed(check_log)
        ])

    # --- the written report -------------------------------------------------------
    report = SCAN_DIR / f"{picked.isoformat()}.md"
    if report.exists():
        with st.expander("Full written report"):
            st.markdown(report.read_text(encoding="utf-8"))
