"""Trading -- the bots' performance: stats, equity, backtest yardstick."""

import plotly.graph_objects as go
import streamlit as st

import analytics
import config
import ui


def render(ctx):
    if ctx.sheet_error:
        st.error(ctx.sheet_error)
        return

    stats = ctx.stats
    n_closed = stats.get("n_closed", 0)

    # --- headline performance ---------------------------------------------
    ui.section("Performance", "Realized results from the bots' trade log")
    if n_closed == 0:
        st.info(
            "No closed trades yet. Everything here lights up the moment a "
            "bot writes its first row with a realized P&L."
        )
    else:
        pf = stats["profit_factor"]
        ui.cards([
            ui.card("Win rate", ui.pct(stats["win_rate"]),
                    note=f'{stats["n_wins"]} of {n_closed} closed trades'),
            ui.card("Total realized P&L",
                    ui.money(stats["total_pnl"], signed=True),
                    tone=ui.tone_of(stats["total_pnl"])),
            ui.card("Expectancy / trade",
                    ui.money(stats["expectancy"], signed=True),
                    tone=ui.tone_of(stats["expectancy"]),
                    note="Average across winners and losers",
                    help="The average dollars the bot makes (or loses) on a "
                         "typical trade, blending wins and losses."),
            ui.card("Profit factor",
                    f"{pf:.2f}" if pf is not None else "—",
                    note="Above 1.0 = profitable",
                    help="Total winnings divided by total losses. Above 1.0 "
                         "means it makes money; 1.5+ is strong."),
        ])
        ui.cards([
            ui.card("Average winner", ui.money(stats["avg_win"], signed=True),
                    tone="good"),
            ui.card("Average loser", ui.money(stats["avg_loss"], signed=True),
                    tone="bad"),
            ui.card("Best trade", ui.money(stats["best"], signed=True),
                    tone=ui.tone_of(stats["best"])),
            ui.card("Worst trade", ui.money(stats["worst"], signed=True),
                    tone=ui.tone_of(stats["worst"])),
        ])

    # --- equity curve --------------------------------------------------------
    curve = analytics.equity_curve(ctx.trades, config.STARTING_CAPITAL)
    if not curve.empty:
        ui.section("Equity curve",
                   f"Anchored at {ui.money(config.STARTING_CAPITAL)} starting capital")
        max_dd = curve["drawdown"].min()
        peak_at_max = curve.loc[curve["drawdown"].idxmin(), "peak"]
        ui.cards([
            ui.card("Current equity", ui.money(curve["equity"].iloc[-1])),
            ui.card("Peak equity", ui.money(curve["peak"].iloc[-1])),
            ui.card("Max drawdown", ui.money(max_dd, signed=True),
                    tone="bad" if max_dd < 0 else "neutral",
                    note=f"{max_dd / peak_at_max:.1%} below peak"
                    if peak_at_max else None),
        ])
        with st.container(border=True):
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=curve["timestamp"], y=curve["peak"], name="Peak",
                line=dict(dash="dot", width=1.2, color="#C7C7CC"),
                hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=curve["timestamp"], y=curve["equity"], name="Equity",
                mode="lines+markers",
                line=dict(width=2.5, color=ui.BLUE),
                marker=dict(size=5),
                hovertemplate="%{y:$,.2f}<extra></extra>",
            ))
            ui.style_fig(fig, height=350)
            st.plotly_chart(fig, config=ui.PLOTLY_CONFIG)

        with st.container(border=True):
            dd = go.Figure(go.Scatter(
                x=curve["timestamp"], y=curve["drawdown"], name="Drawdown",
                fill="tozeroy", line=dict(width=1.2, color=ui.RED),
                fillcolor="rgba(255,59,48,0.10)",
                hovertemplate="%{y:$,.2f}<extra></extra>",
            ))
            ui.style_fig(dd, height=170, legend=False)
            st.plotly_chart(dd, config=ui.PLOTLY_CONFIG)

    # --- backtest vs live ------------------------------------------------------
    bt = config.BACKTEST
    head_l, head_r = st.columns([5, 1], vertical_alignment="bottom")
    with head_l:
        ui.section(
            "Backtest vs. live",
            f"The locked Phase 5 profile: about +{bt['expected_annual_r']:g}R per "
            f"year, ~{bt['expected_win_rate']:.0%} win rate, winners near "
            f"+{bt['expected_avg_winner_r']:g}R. {bt['note']}",
        )
    with head_r:
        with st.popover("1R", help="Dollars risked per trade"):
            r_dollars = st.number_input(
                "1R — dollars risked per trade",
                min_value=1.0,
                value=float(config.R_DOLLARS),
                step=50.0,
                key="r_dollars",
                help="Match this to the per-trade risk the bot's "
                     "risk_manager uses, or edit the default in config.py.",
            )

    report = analytics.r_report(ctx.trades, st.session_state.get("r_dollars", config.R_DOLLARS), bt)
    if report.get("n_closed", 0) == 0:
        st.info("This panel wakes up after the first closed trade.")
        return

    n = report["n_closed"]
    if n < 30:
        st.warning(
            f"Only {n} closed trade{'s' if n != 1 else ''} so far — far too "
            "few to accept or reject the backtest. At a ~30% win rate, a run "
            "of 8–10 straight losses is statistically ordinary. Judge "
            "execution quality at this sample size, not P&L."
        )

    run = analytics.streaks(ctx.trades)
    ui.cards([
        ui.card("Win rate", ui.pct(report["win_rate"]),
                note=f"Backtest: ~{bt['expected_win_rate']:.0%}"),
        ui.card(
            "Average winner",
            f"+{report['avg_winner_r']:.2f}R" if report["avg_winner_r"] else "—",
            note=f"Backtest: near +{bt['expected_avg_winner_r']:g}R",
        ),
        ui.card(
            "Cumulative result", f"{report['cum_r']:+.2f}R",
            tone=ui.tone_of(report["cum_r"]),
            note=f"Backtest pace to date: {report['expected_to_date']:+.2f}R",
        ),
        ui.card(
            "Longest losing streak", f"{run['max_losing']} trades",
            note="Expected under this profile",
        ),
    ])
    if run["current_kind"] == "losing" and run["current_len"] >= 3:
        st.caption(
            f"Currently {run['current_len']} losses in a row. The profile "
            "says hold the process steady."
        )

    with st.container(border=True):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=report["expected_series"]["timestamp"],
            y=report["expected_series"]["expected_r"],
            name="Backtest pace",
            line=dict(dash="dash", width=1.3, color="#A8A8AD"),
            hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=report["cum_series"]["timestamp"],
            y=report["cum_series"]["cum_r"],
            name="Actual",
            mode="lines+markers",
            line=dict(width=2.5, shape="hv", color=ui.BLUE),
            marker=dict(size=5),
            hovertemplate="%{y:+.2f}R<extra></extra>",
        ))
        fig.add_hline(y=0, line_width=1, opacity=0.35)
        ui.style_fig(fig, height=350)
        st.plotly_chart(fig, config=ui.PLOTLY_CONFIG)
    st.caption(
        f"1R = {ui.money(st.session_state.get('r_dollars', config.R_DOLLARS))} — "
        "adjust it from the 1R control above."
    )

    # --- positions + log ----------------------------------------------------------
    if not ctx.trades.empty:
        ui.section("Open positions", "Inferred by pairing open rows against close rows")
        open_df = analytics.open_positions(ctx.trades)
        if open_df.empty:
            st.caption("Nothing open right now.")
        else:
            st.dataframe(open_df, hide_index=True, width="stretch")
            st.caption("If this ever disagrees with Alpaca, trust Alpaca.")

        ui.section("Recent closed trades")
        recent = analytics.closed_trades(ctx.trades).tail(15).iloc[::-1]
        if recent.empty:
            st.caption("None yet.")
        else:
            shown = [
                c for c in recent.columns
                if c not in ("closed",) and not recent[c].isna().all()
            ]
            st.dataframe(recent[shown], hide_index=True, width="stretch")
