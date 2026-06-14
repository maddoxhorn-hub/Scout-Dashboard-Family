"""Overview -- the one-glance screen: balances, status, this month."""

from datetime import date

import plotly.graph_objects as go
import streamlit as st

import analytics
import config
import ui
from budget import store


def render(ctx):
    if ctx.sheet_error:
        st.error(ctx.sheet_error)

    # --- balances --------------------------------------------------------
    ui.cards([
        ui.card(
            "Everything combined",
            ui.money((ctx.schwab_total or 0) + ctx.bot_equity)
            if ctx.schwab_total is not None else ui.money(ctx.bot_equity),
            note="Schwab + bot account" if ctx.schwab_total is not None
            else "Bot account only — Schwab pending",
        ),
        ui.card(
            "Schwab",
            ui.money(ctx.schwab_total) if ctx.schwab_total is not None
            else "Not connected",
            dim=ctx.schwab_total is None,
            note=None if ctx.schwab_total is None
            else f"{len(ctx.schwab_accounts)} account(s)",
        ),
        ui.card("Bot account (paper)", ui.money(ctx.bot_equity),
                note=f"Started at {ui.money(config.STARTING_CAPITAL)}"),
        ui.card(
            "Bot P&L today",
            ui.money(ctx.stats.get("today_pnl", 0.0), signed=True),
            tone=ui.tone_of(ctx.stats.get("today_pnl", 0.0)),
        ),
    ])

    # --- this month ------------------------------------------------------
    txns = store.transactions_cached()
    month_label = f"{date.today():%B}"
    if txns.empty:
        spent_card = ui.card(
            f"Spending · {month_label}", "No data",
            note="Import a bank CSV in Budget", dim=True,
        )
        net_card = ui.card(f"Cash flow · {month_label}", "—", dim=True)
    else:
        this_month = txns[txns["date"].dt.to_period("M") == date.today().strftime("%Y-%m")]
        spending = -this_month.loc[
            (this_month["amount"] < 0)
            & ~this_month["category"].isin(store.NON_SPENDING),
            "amount",
        ].sum()
        income = this_month.loc[
            (this_month["amount"] > 0)
            & (this_month["category"] != "Transfers & Payments"),
            "amount",
        ].sum()
        net = income - spending
        spent_card = ui.card(f"Spending · {month_label}", ui.money(spending))
        net_card = ui.card(
            f"Cash flow · {month_label}", ui.money(net, signed=True),
            tone=ui.tone_of(net), note="Income minus spending",
        )

    n_closed = ctx.stats.get("n_closed", 0)
    open_df = analytics.open_positions(ctx.trades) if not ctx.trades.empty else None
    n_open = 0 if open_df is None or open_df.empty else len(open_df)

    ui.cards([
        spent_card,
        net_card,
        ui.card(
            "Win rate",
            ui.pct(ctx.stats["win_rate"]) if n_closed else "—",
            note=f"{n_closed} closed trade{'s' if n_closed != 1 else ''}"
            if n_closed else "No closed trades yet",
            dim=not n_closed,
        ),
        ui.card(
            "Open positions",
            str(n_open),
            note="Inferred from the bots' log",
        ),
    ])

    # --- equity sparkline ---------------------------------------------------
    curve = analytics.equity_curve(ctx.trades, config.STARTING_CAPITAL)
    if curve.empty:
        ui.section("Bot equity", "Realized, after each closed trade")
        st.caption("Your equity chart appears here after the first closed trade.")
    if not curve.empty:
        ui.section("Bot equity", "Realized, after each closed trade")
        with st.container(border=True):
            fig = go.Figure(
                go.Scatter(
                    x=curve["timestamp"], y=curve["equity"],
                    mode="lines", line=dict(width=2.5, color=ui.BLUE),
                    fill="tozeroy", fillcolor="rgba(0,113,227,0.06)",
                    name="Equity", hovertemplate="%{y:$,.2f}<extra></extra>",
                )
            )
            fig.update_yaxes(rangemode="tozero")
            ui.style_fig(fig, height=230, legend=False)
            st.plotly_chart(fig, config=ui.PLOTLY_CONFIG)

    # --- connections ----------------------------------------------------------
    ui.section("Connections")
    sheet_state = ("off", "Trade log (Google Sheet)", "error — see message above") \
        if ctx.sheet_error else ("on", "Trade log (Google Sheet)", "Connected · read-only")
    if ctx.schwab_error == "not_configured":
        schwab_state = ("wait", "Schwab", "Waiting on API approval")
    elif ctx.schwab_error == "no_token":
        schwab_state = ("wait", "Schwab", "Keys saved — run schwab_login.py")
    elif ctx.schwab_error:
        schwab_state = ("off", "Schwab", "Login expired — run schwab_login.py")
    else:
        schwab_state = ("on", "Schwab", f"{len(ctx.schwab_accounts)} account(s) · read-only")

    from budget import plaid_sync

    plaid_state = plaid_sync.setup_state()
    if plaid_state == "ready":
        n_linked = len(plaid_sync.linked_items())
        detail = f"Plaid · {n_linked} bank(s) linked"
        if not txns.empty:
            detail += f" · {len(txns):,} transactions"
        bank_state = ("on", "Banks (Discover · Amex · KeyBank)", detail)
    elif plaid_state == "no_items":
        bank_state = (
            "wait", "Banks (Discover · Amex · KeyBank)",
            "Plaid keys set — run plaid_link.py per bank",
        )
    elif txns.empty:
        bank_state = ("off", "Banks (Discover · Amex · KeyBank)", "No imports yet")
    else:
        accounts = store.accounts_summary()
        last = accounts["last"].max()
        bank_state = (
            "on", "Banks (Discover · Amex · KeyBank)",
            f"{int(accounts['transactions'].sum()):,} transactions · through {last}",
        )

    ui.status_list([sheet_state, schwab_state, bank_state])
