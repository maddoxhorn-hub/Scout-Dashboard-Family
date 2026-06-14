"""Markets -- watch tickers live, catch reversals, trade practice money.

The page is a window onto market/watcher.py's once-a-minute loop: the
watchlist (scan picks + hand-added tickers), the tripwire alert feed,
and a paper-trading account that fills at real quoted prices. Practice
money only -- nothing on this page can touch a real account.
"""

import plotly.graph_objects as go
import streamlit as st

import ui
from market import feed, paper, tripwires, watcher, watchlist


def _plain(symbol: str) -> str:
    return symbol.split(":")[-1]


def render():
    _market_pulse()

    state = watcher.latest()
    quotes = state.get("quotes", {})
    items = watchlist.all_items()

    # First visit before the watcher's first pass: fetch once directly
    # so the page never opens empty-handed.
    needed = {i["symbol"] for i in items} | {p["symbol"] for p in paper.positions()}
    if needed - set(quotes):
        with st.spinner("Getting live prices…"):
            quotes = {**quotes, **feed.quotes(needed - set(quotes))}

    phase = state.get("phase") or feed.market_phase()
    updated = (state.get("updated_at") or "")[11:16]
    caption = feed.PHASE_LABEL.get(phase, "Market")
    if updated:
        caption += f" · prices as of {updated} ET"
    ui.section("Markets", f"{caption} · practice money only — nothing "
                          "here can touch a real account")

    today = feed.now_et().strftime("%Y-%m-%d")
    alerts_today = [a for a in watcher.alerts() if a.get("date") == today]
    summ = paper.summary(quotes)

    ui.cards([
        ui.card("Practice account", ui.money(summ["equity"]),
                tone=ui.tone_of(summ["total_pnl"]),
                note=f"{ui.money(summ['total_pnl'], signed=True)} all time",
                note_tone=ui.tone_of(summ["total_pnl"])),
        ui.card("Cash", ui.money(summ["cash"]),
                note="ready to invest"),
        ui.card("Today", ui.money(summ["day_pnl"], signed=True),
                tone=ui.tone_of(summ["day_pnl"]),
                note="across open positions"),
        ui.card("Alerts today", f"{len(alerts_today)}",
                tone="bad" if alerts_today else "neutral",
                note="see the feed below" if alerts_today else "all quiet"),
    ])

    _watchlist_section(items, quotes, state)
    _alerts_section(alerts_today)
    _paper_section(quotes)


# ----------------------------------------------------------------------
# Auto-refresh -- rerun the page when the watcher writes something new
# ----------------------------------------------------------------------

@st.fragment(run_every="10s")
def _market_pulse():
    signal = watcher.change_signal()
    previous = st.session_state.get("_market_signal")
    st.session_state["_market_signal"] = signal
    if previous is not None and signal != previous:
        st.rerun(scope="app")


# ----------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------

_DIRECTION_PILL = {
    1: ("▲ betting up", "green"),
    -1: ("▼ betting down", "red"),
}
_CONFIDENCE_PILL = {"High": "blue", "Medium": "orange", "Speculative": "gray"}


def _watchlist_section(items, quotes, state):
    ui.section("Watchlist",
               "The tickers being watched once a minute — wires trip when "
               "a move starts breaking")

    if not items:
        st.info(
            "Nothing on the list yet. Add a ticker below and which way "
            "you think it's headed — Scout checks it every minute the "
            "market is open and pops a notification if the move turns "
            "around."
        )

    wires_state = state.get("wires", {})
    today = feed.now_et().strftime("%Y-%m-%d")

    for item in items:
        symbol = item["symbol"]
        quote = quotes.get(symbol) or {}
        close = quote.get("close")
        change = quote.get("change")
        sign = tripwires.direction_sign(item.get("direction"))
        label, color = _DIRECTION_PILL[sign]

        with st.container(border=True):
            c_name, c_dir, c_now, c_since, c_x = st.columns(
                [2.4, 1.5, 1.3, 1.5, 0.5], vertical_alignment="center"
            )
            with c_name:
                desc = quote.get("description") or ""
                st.html(
                    f'<div style="font-weight:700;font-size:16px;">{_plain(symbol)}'
                    f' <span style="color:{ui.INK_FAINT};font-weight:500;'
                    f'font-size:12.5px;">{desc[:34]}</span></div>'
                )
            with c_dir:
                pills = ui.pill(label, color)
                conf = item.get("confidence")
                if conf:
                    pills += " " + ui.pill(conf, _CONFIDENCE_PILL.get(conf, "gray"))
                fired = [
                    code for code, day in
                    wires_state.get(symbol, {}).get("fired", {}).items()
                    if day == today and code != "judged"
                ]
                if fired:
                    pills += " " + ui.pill(f"{len(fired)} wire{'s' if len(fired) > 1 else ''} tripped", "red")
                st.html(pills)
            with c_now:
                if close:
                    tone = ui.tone_of(change)
                    st.html(
                        f'<div style="font-weight:700;font-size:17px;'
                        f'font-variant-numeric:tabular-nums;">{ui.money(close)}</div>'
                        f'<div style="font-size:12.5px;font-weight:600;" class="k-note {tone}">'
                        f'{change:+.2f}% today</div>'
                    )
                else:
                    st.html(f'<span style="color:{ui.INK_FAINT};">no quote</span>')
            with c_since:
                entry = item.get("entry_price")
                if entry and close:
                    drift = (close - entry) / entry * 100
                    going_well = drift * sign >= 0
                    tone = "good" if going_well else "bad"
                    st.html(
                        f'<div style="font-size:12.5px;color:{ui.INK_FAINT};'
                        f'font-weight:500;">picked at {ui.money(entry)}</div>'
                        f'<div style="font-size:14px;font-weight:650;" class="k-note {tone}">'
                        f'{drift:+.2f}% since</div>'
                    )
            with c_x:
                if item["source"] == "manual":
                    if st.button("✕", key=f"unwatch_{symbol}",
                                 help=f"Stop watching {_plain(symbol)}"):
                        watchlist.remove(symbol)
                        st.rerun()
            thesis = item.get("thesis")
            if thesis:
                st.caption(thesis)

    _add_form()
    _today_chart(items, state)


def _add_form():
    with st.form("watch_add", border=False):
        c1, c2, c3 = st.columns([2, 1.6, 1], vertical_alignment="bottom")
        with c1:
            raw = st.text_input("Watch a ticker",
                                placeholder="e.g. AAPL or TSLA")
        with c2:
            direction = st.selectbox(
                "Your hunch", ["Going up", "Going down"],
                help="Which way you think it's headed — the tripwires "
                     "watch for the opposite",
            )
        with c3:
            submitted = st.form_submit_button("Watch", type="primary",
                                              width="stretch")
    if submitted and raw.strip():
        with st.spinner("Looking it up…"):
            symbol = feed.resolve(raw)
        if symbol is None:
            st.error(f"Couldn't find “{raw.strip().upper()}” on a US exchange.")
        else:
            quote = feed.quotes([symbol]).get(symbol, {})
            watchlist.add(
                symbol,
                "up" if direction == "Going up" else "down",
                quote.get("close"),
            )
            st.toast(f"Watching {_plain(symbol)}")
            st.rerun()


def _today_chart(items, state):
    history = state.get("history") or {}
    series = {
        sym: pts for sym, pts in history.items()
        if len(pts) >= 2 and sym in {i["symbol"] for i in items}
    }
    if not series:
        return
    with st.expander("Today's moves, minute by minute"):
        fig = go.Figure()
        for sym, points in series.items():
            base = points[0][1]
            fig.add_trace(go.Scatter(
                x=[p[0] for p in points],
                y=[(p[1] / base - 1) * 100 for p in points],
                mode="lines", name=_plain(sym),
                hovertemplate=f"{_plain(sym)} %{{x}}: %{{y:+.2f}}%<extra></extra>",
            ))
        fig.add_hline(y=0, line_color="#D8D8DC", line_width=1)
        ui.style_fig(fig, height=300)
        fig.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig, config=ui.PLOTLY_CONFIG)


# ----------------------------------------------------------------------
# Alert feed
# ----------------------------------------------------------------------

_WIRE_PILL_TEXT = {
    "move_against": "moved against",
    "vwap_cross": "VWAP cross",
    "gave_back": "gave it back",
    "rsi_hook": "RSI hook",
    "claude": "Claude's take",
}


def _alerts_section(alerts_today):
    ui.section("Alerts", "Tripwires that fired today — newest first")

    judge_row = st.container()
    with judge_row:
        if watcher.claude_available():
            current = watcher.settings().get("claude_judge", False)
            chosen = st.toggle(
                "Ask Claude to judge each alert",
                value=current,
                help="When a wire trips, a short Claude run reads the news "
                     "and says whether it looks like a real reversal or "
                     "noise. Uses a little of the Claude plan each time.",
            )
            if chosen != current:
                watcher.save_settings(claude_judge=chosen)
                st.toast("Claude judging is " + ("on" if chosen else "off"))

    if not alerts_today:
        st.caption("Nothing has tripped today.")
        return

    with st.container(border=True):
        for alert in alerts_today[:30]:
            code = alert.get("code", "")
            pill_color = "blue" if code == "claude" else "orange"
            st.html(
                f'<div class="rowline">'
                f'<span style="color:{ui.INK_FAINT};font-variant-numeric:'
                f'tabular-nums;flex:0 0 44px;">{alert.get("time", "")}</span>'
                f'<b style="flex:0 0 56px;">{_plain(alert.get("symbol", ""))}</b>'
                f'{ui.pill(_WIRE_PILL_TEXT.get(code, code), pill_color)}'
                f'<span style="color:{ui.INK_SOFT};">{alert.get("message", "")}</span>'
                f"</div>"
            )


# ----------------------------------------------------------------------
# Paper trading
# ----------------------------------------------------------------------

def _paper_section(quotes):
    ui.section("Paper trading",
               "Practice with pretend money at real prices — fills use the "
               "latest quote")

    positions = paper.positions()
    if positions:
        rows = []
        for pos in positions:
            quote = quotes.get(pos["symbol"]) or {}
            close = quote.get("close")
            value = pnl = pnl_pct = None
            if close:
                value = pos["qty"] * close
                pnl = (close - pos["avg_cost"]) * pos["qty"]
                if pos["avg_cost"]:
                    pnl_pct = (close / pos["avg_cost"] - 1) * 100
                    if pos["qty"] < 0:
                        pnl_pct = -pnl_pct
            rows.append({
                "Symbol": _plain(pos["symbol"]),
                "Shares": pos["qty"],
                "Avg cost": pos["avg_cost"],
                "Last": close,
                "Value": value,
                "P/L $": pnl,
                "P/L %": pnl_pct,
            })
        import pandas as pd

        frame = pd.DataFrame(rows)
        styled = frame.style.format({
            "Shares": "{:,.0f}", "Avg cost": "${:,.2f}", "Last": "${:,.2f}",
            "Value": "${:,.2f}", "P/L $": "${:+,.2f}", "P/L %": "{:+.2f}%",
        }, na_rep="—").map(
            lambda v: f"color: {ui.GREEN}" if isinstance(v, (int, float)) and v > 0
            else (f"color: {ui.RED}" if isinstance(v, (int, float)) and v < 0 else ""),
            subset=["P/L $", "P/L %"],
        )
        st.dataframe(styled, hide_index=True, width="stretch")
        if any(r["Shares"] < 0 for r in rows):
            st.caption(
                "Negative shares = a short: you sold borrowed shares and "
                "profit if the price falls."
            )
    else:
        st.caption("No positions yet — your first practice trade goes below.")

    _trade_form(quotes)

    with st.expander("Trade history & account"):
        history = paper.trades_frame()
        if history.empty:
            st.caption("No trades yet.")
        else:
            st.dataframe(history, hide_index=True, width="stretch")
        st.caption(
            f"The account started with {ui.money(paper.STARTING_CASH, decimals=0)} "
            "of practice money. Everything lives in data/paper.db on this "
            "machine."
        )
        sure = st.checkbox("I want to wipe the practice account and start over")
        if st.button("Reset practice account", disabled=not sure):
            paper.reset()
            st.toast("Practice account reset")
            st.rerun()


def _trade_form(quotes):
    with st.form("paper_trade", border=False):
        c1, c2, c3, c4 = st.columns([1.6, 1.2, 1.2, 1], vertical_alignment="bottom")
        with c1:
            raw = st.text_input("Ticker", placeholder="e.g. AAPL")
        with c2:
            side = st.selectbox("Action", ["Buy", "Sell"])
        with c3:
            qty = st.number_input("Shares", min_value=1, step=1, value=10)
        with c4:
            submitted = st.form_submit_button("Place practice trade",
                                              type="primary", width="stretch")
    if not submitted:
        return
    if not raw.strip():
        st.error("Type a ticker first.")
        return
    with st.spinner("Getting the current price…"):
        symbol = feed.resolve(raw)
        quote = (quotes.get(symbol) or feed.quotes([symbol]).get(symbol, {})) \
            if symbol else {}
    price = quote.get("close")
    if not price:
        st.error(f"Couldn't get a price for “{raw.strip().upper()}”.")
        return
    try:
        paper.trade(symbol, side.lower(), qty, price)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.toast(f"{side} {qty:,} {_plain(symbol)} @ {ui.money(price)} — practice fill")
    st.rerun()
