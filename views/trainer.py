"""Trainer -- a blinded chart-reading game that measures Maddox's judgment.

Shows a real historical snapshot (ticker + future hidden) with his full
indicator stack across 2m/10m/1h. He calls Bullish / Bearish / Pass with a
confidence; the call is logged and scored against the hidden outcome, then the
answer is revealed. Analytics track his real hit rate and where his edge lives.
All rendering is from market/trainer.py's stored payload -- nothing leaks.
"""

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import ui
from market import trainer

# TradingView-ish dark palette for the chart panel
BG = "#131722"
UP, DOWN = "#26a69a", "#ef5350"

# Per-cloud colors, in the order of trainer.RIPSTER_PAIRS:
#   0: 8/9   1: 5/13   2: 34/50   3: 72/89   4: 180/200
# Only cloud #2 (34/50) is the orange<->blue cloud that runs through the
# candles -- the only orange indicator, per the real TradingView setup.
# The others are quiet, non-orange backdrops until exact Style colors are set.
_GRAY = "rgba(120,144,156,{a})"
CLOUD_STYLE = [
    {"bull": _GRAY, "bear": _GRAY, "op": 0.09, "show": False},               # 8/9
    {"bull": _GRAY, "bear": _GRAY, "op": 0.09, "show": False},               # 5/13
    {"bull": "rgba(41,98,255,{a})", "bear": "rgba(255,149,0,{a})", "op": 0.34, "show": True},  # 34/50
    {"bull": _GRAY, "bear": _GRAY, "op": 0.07, "show": False},               # 72/89
    {"bull": _GRAY, "bear": _GRAY, "op": 0.06, "show": False},               # 180/200
]


def _sma(vals, n):
    out = []
    for i in range(len(vals)):
        w = [v for v in vals[max(0, i - n + 1):i + 1] if v is not None]
        out.append(sum(w) / len(w) if w else None)
    return out
_LEVELS = {
    "premarket_high": ("#00bcd4", "PM high"), "premarket_low": ("#00bcd4", "PM low"),
    "orb_high": ("#ff9800", "ORB high"), "orb_low": ("#ff9800", "ORB low"),
    "prior_day_high": ("#9e9e9e", "PD high"), "prior_day_low": ("#9e9e9e", "PD low"),
}


def _bicolor_cloud(fig, x, fast, slow, bull_color, bear_color, opacity):
    """Fill between fast/slow EMAs: bull_color where fast>=slow, bear_color
    where fast<slow (a cloud with bull==bear is single-colored)."""
    bull_lo = [s if (f is not None and s is not None and f >= s) else None
               for f, s in zip(fast, slow)]
    bull_hi = [f if (f is not None and s is not None and f >= s) else None
               for f, s in zip(fast, slow)]
    bear_lo = [s if (f is not None and s is not None and f < s) else None
               for f, s in zip(fast, slow)]
    bear_hi = [f if (f is not None and s is not None and f < s) else None
               for f, s in zip(fast, slow)]
    for lo, hi, color in ((bull_lo, bull_hi, bull_color), (bear_lo, bear_hi, bear_color)):
        fig.add_trace(go.Scatter(x=x, y=lo, mode="lines", line=dict(width=0),
                                 connectgaps=False, hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=hi, mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=color.format(a=opacity),
                                 connectgaps=False, hoverinfo="skip", showlegend=False))


def _chart(tf_data, levels, zoom=1.0, uirev=None):
    b = tf_data["bars"]
    x = [r["t"][5:] for r in b]   # "MM-DD HH:MM"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.8, 0.2])
    # Only the 34/50 cloud is shown (orange/blue), like the real chart.
    for cl, sty in zip(tf_data["clouds"], CLOUD_STYLE):
        if sty.get("show"):
            _bicolor_cloud(fig, x, cl["fast"], cl["slow"], sty["bull"], sty["bear"], sty["op"])
    # candles
    fig.add_trace(go.Candlestick(
        x=x, open=[r["o"] for r in b], high=[r["h"] for r in b],
        low=[r["l"] for r in b], close=[r["c"] for r in b],
        increasing_line_color=UP, decreasing_line_color=DOWN, name="", showlegend=False), row=1, col=1)
    # MAs + VWAP, colored to match the real chart: EMA8 green, its SMA-5
    # smoothing yellow, EMA21 red, SMA200 orange-dotted, VWAP white.
    ema_smooth = _sma(tf_data["ema8"], 5)
    for series, color, name, dash, width in (
            (tf_data["ema8"], "#4caf50", "EMA 8", None, 1.4),
            (ema_smooth, "#ffd54f", "MA 5", None, 1.2),
            (tf_data["ema21"], "#ef5350", "EMA 21", None, 1.4),
            (tf_data["sma200"], "#ff9800", "SMA 200", "dot", 1.5),
            (tf_data["vwap"], "#ffffff", "VWAP", None, 1.2)):
        fig.add_trace(go.Scatter(x=x, y=series, mode="lines", name=name,
                                 line=dict(color=color, width=width, dash=dash),
                                 connectgaps=False, hoverinfo="skip"), row=1, col=1)
    # horizontal levels
    for k, (color, lab) in _LEVELS.items():
        if k in levels:
            fig.add_hline(y=levels[k], line=dict(color=color, width=1, dash="dash"),
                          opacity=0.6, annotation_text=lab,
                          annotation_position="right",
                          annotation_font=dict(size=9, color=color), row=1, col=1)
    # volume
    fig.add_trace(go.Bar(x=x, y=[r["v"] for r in b],
                         marker_color=[UP if r["c"] >= r["o"] else DOWN for r in b],
                         opacity=0.5, showlegend=False, hoverinfo="skip"), row=2, col=1)
    fig.update_layout(
        height=620, margin=dict(l=4, r=48, t=8, b=4),
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color="#d1d4dc", size=11),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=10),
                    bgcolor="rgba(0,0,0,0)"),
        dragmode="pan",      # click-drag PANS (TradingView feel) — no box zoom
        # uirevision preserves a manual axis-drag zoom across reruns; it's keyed
        # to (snapshot, tf, zoom) so the slider still takes effect when changed.
        uirevision=uirev,
    )
    for r in (1, 2):
        fig.update_xaxes(type="category", showgrid=False, row=r, col=1,
                         nticks=8, tickangle=0, fixedrange=False)
        fig.update_yaxes(gridcolor="#1f2a37", row=r, col=1, side="right",
                         fixedrange=False)   # draggable price axis (vertical zoom)
    # base range = the candles (not SMA200/slow clouds), so the action fills the
    # panel; the `zoom` factor tightens it around the latest price.
    lows = [r["l"] for r in b]
    highs = [r["h"] for r in b]
    pad = (max(highs) - min(lows)) * 0.08 or max(highs) * 0.01
    if zoom and zoom > 1:
        center = b[-1]["c"]
        half = (max(highs) - min(lows) + 2 * pad) / (2 * zoom)
        yr = [center - half, center + half]
    else:
        yr = [min(lows) - pad, max(highs) + pad]
    fig.update_yaxes(range=yr, row=1, col=1)
    return fig


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_chart(snap_id, tf, zoom):
    """Build the figure once per (snapshot, timeframe, zoom) so moving the
    confidence slider (or any rerun) doesn't rebuild it — keeps it snappy."""
    snap = next((s for s in trainer.pool() if s["id"] == snap_id), None)
    if not snap:
        return None
    return _chart(snap["tf"][tf], snap["levels"], zoom=zoom,
                  uirev=f"{snap_id}|{tf}|{zoom}")


def _ask_block(snap):
    top = st.columns([3, 2], vertical_alignment="bottom")
    with top[0]:
        tf = st.segmented_control("Timeframe", ["2m", "10m", "1h"], default="2m",
                                  key="tf_pick", label_visibility="collapsed") or "2m"
    with top[1]:
        zoom = st.select_slider("Vertical zoom", options=[1.0, 1.5, 2.0, 3.0, 4.0],
                                value=1.0, format_func=lambda z: "Fit" if z == 1
                                else f"{z:g}×", key="vzoom",
                                help="Stretch the price axis to see small moves. "
                                     "You can also drag the right-hand price scale.")
    st.plotly_chart(_cached_chart(snap["id"], tf, zoom),
                    config={"scrollZoom": True, "displayModeBar": False},
                    key=f"chart_{snap['id']}_{tf}_{zoom}")
    st.caption("Vertical zoom slider above (or drag the right-hand price scale) "
               "· scroll to zoom · click-drag to pan · double-click to reset.")
    conf = st.select_slider("Confidence", options=[1, 2, 3, 4, 5], value=3,
                            key="conf", help="5 = an A+ setup you'd size up on")
    c1, c2, c3 = st.columns(3)
    with c1:
        bull = st.button("📈 Bullish", width="stretch", type="primary")
    with c2:
        bear = st.button("📉 Bearish", width="stretch")
    with c3:
        skip = st.button("⊘ Pass / no setup", width="stretch")
    if bull or bear or skip:
        label = "bull" if bull else ("bear" if bear else "pass")
        result = trainer.record(snap, label, int(conf))
        st.session_state["trainer_result"] = result
        st.session_state.pop("trainer_snap", None)
        st.rerun()


def _pct(v, dec=2):
    return f"{v*100:+.{dec}f}%" if v is not None else "—"


def _reveal_block(res):
    g = res.get("grade")
    if res["label"] == "pass":
        ui.section("You passed", "No call scored — that's a valid read.")
    elif g == "hit":
        ui.section("✓ Correct", f"Your {res['label'].upper()} call caught a "
                   f"{_pct(res.get('fav_move'), 1)} move within ~3 days — the "
                   "kind of swing a multi-day contract rides.")
    elif g == "miss":
        ui.section("✗ Missed", f"It moved decisively against your "
                   f"{res['label'].upper()} call over the next ~3 days.")
    else:
        ui.section("↔ No decisive move", "It chopped sideways — no real swing "
                   "either way, so this one isn't scored (not counted for or "
                   "against you).")
    mfe, mae = res.get("mfe_3d"), res.get("mae_3d")
    ui.cards([
        ui.card("Ticker (was hidden)", res["ticker"]),
        ui.card("Biggest 3-day rise", _pct(mfe, 1), tone="good",
                help="How far it ran UP at best over the next ~3 sessions — "
                     "what a call could have captured."),
        ui.card("Biggest 3-day drop", _pct(mae, 1), tone="bad",
                help="How far it fell at worst over the next ~3 sessions — "
                     "what a put could have captured."),
        ui.card("Where it closed (3d)", _pct(res.get("fwd_3d")),
                tone=ui.tone_of(res.get("fwd_3d")),
                note=f"2h: {_pct(res.get('fwd_2h'))}"),
    ])
    _explain_setup(res)
    if st.button("Next chart →", type="primary"):
        st.session_state.pop("trainer_result", None)
        st.rerun()


def _explain_setup(res):
    """Tell her WHY: which conditions were for/against her call, and how she's
    historically done on this kind of setup. This is the learning made visible."""
    ex = trainer.explain(res)
    if not ex:
        return
    g = res.get("grade")
    if g == "miss":
        ui.section("Why this was a tough setup",
                   "The conditions that were working against your call")
        if ex["against"]:
            st.markdown("**Against your " + res["label"].upper() + " call:** "
                        + " · ".join(ex["against"]))
        if ex["aligned"]:
            st.caption("In your favor: " + " · ".join(ex["aligned"]))
        st.caption("The Trainer logs this setup so it learns the patterns that "
                   "trip you up — and warns you when one shows up again.")
    elif g == "hit":
        ui.section("Why this setup worked", "What lined up behind your call")
        if ex["aligned"]:
            st.markdown("**In your favor:** " + " · ".join(ex["aligned"]))
        if ex["against"]:
            st.caption("Despite: " + " · ".join(ex["against"]))
    if ex["rate"]["acc"] is not None and ex["rate"]["n"] >= 2:
        st.caption(f"📊 On **{ex['signature']}**, you've been right "
                   f"{ex['rate']['acc']*100:.0f}% across {ex['rate']['n']} similar calls.")


def _analytics():
    a = trainer.analytics()
    ui.section("Your track record", "Each call is scored on the next ~3 days "
               "(matching multi-day contracts) — the real measure of your read")
    if a["total"] == 0:
        st.caption("No calls yet. Make some above and your hit rate builds here.")
        return
    acc = a.get("accuracy")
    cards = [
        ui.card("Calls logged", str(a["total"]),
                note=f"{a['directional']} scored · {a.get('chop', 0)} no-move · "
                     f"{a['passes']} passes"),
        ui.card("Hit rate (3-day)", ui.pct(acc) if acc is not None else "—",
                tone="good" if acc and acc > 0.55 else ("bad" if acc and acc < 0.45 else "neutral"),
                note="50% = coin flip",
                help="Of your decisive calls, how often the chart made a real "
                     "(3%+) move your way within ~3 days, bigger than the move "
                     "against you. Sideways/no-move charts aren't counted."),
    ]
    if a.get("ci"):
        cards.append(ui.card("Likely true range",
                             f"{a['ci'][0]*100:.0f}–{a['ci'][1]*100:.0f}%",
                             note="narrows as you log more calls",
                             help="Where your real accuracy probably sits. A "
                                  "small sample is uncertain; this tightens "
                                  "with every call you make."))
    if a.get("high_conf_acc") is not None:
        cards.append(ui.card("High-confidence (4–5)", ui.pct(a["high_conf_acc"]),
                             tone="good" if a["high_conf_acc"] > 0.55 else "neutral",
                             note=f"{a['high_conf_n']} calls — your A+ setups"))
    ui.cards(cards)
    if a.get("by_confidence"):
        ui.row_list([(f"Confidence {k}/5", ui.pct(v)) for k, v in a["by_confidence"].items()])


_FEATURE_TITLE = {
    "cloud_3450": "34/50 cloud", "vs_vwap": "vs VWAP", "ema_stack": "EMA 8 vs 21",
    "short_trend": "short-term trend", "regime": "1h regime (200-SMA)",
}
_VALUE_TITLE = {
    "bull": "blue / bullish", "bear": "orange / bearish",
    "above": "above", "below": "below", "8>21": "8 over 21", "8<21": "8 under 21",
    "rising": "rising", "falling": "falling", "above200": "above", "below200": "below",
}


def _patterns():
    own_n, seed_n, partner_n = trainer.pool_sources()
    has_pool = (seed_n + partner_n) > 0
    if has_pool:
        new = st.toggle(
            f"Learn from the shared pool · +{seed_n + partner_n} reads "
            "(weighted toward the trusted set)",
            value=trainer.pool_enabled(), key="trainer_pool_toggle",
            help="On: the bot also learns from the seed/partner reads bundled "
                 "with this copy, weighting the trusted set higher. Off: only "
                 "your own calls. Your personal hit rate above is always just "
                 "you, either way.")
        if new != trainer.pool_enabled():
            trainer.set_pool_enabled(new)
            st.rerun()

    p = trainer.patterns(min_n=3)
    if p["n"] < 4:
        ui.section("What the Trainer is learning",
                   "Patterns appear once enough scored calls are in the pool")
        st.caption(f"{p['n']} scored so far — keep going and edges and blind "
                   "spots show up here.")
        return
    sub = ("Built from the shared pool — weighted toward the trusted reads"
           if p.get("pooled") and has_pool
           else "Built from your own scored calls")
    ui.section("What the Trainer is learning about your reads",
               sub + " — where the edge lives and which setups tend to burn you")
    if p["strong"]:
        st.markdown("**🟢 Your edges** — setups you read well:")
        for s in p["strong"][:3]:
            st.markdown(f"- {s['text']} — **{s['acc']*100:.0f}%** ({s['n']} calls)")
    if p["weak"]:
        st.markdown("**🔴 Blind spots** — setups that have gone against you:")
        for s in p["weak"][:3]:
            st.markdown(f"- {s['text']} — only **{s['acc']*100:.0f}%** ({s['n']} calls)")
    if not p["strong"] and not p["weak"]:
        st.caption("No strong edge or clear blind spot yet — your reads are "
                   "fairly even across setups so far.")
    with st.expander("Hit rate by condition"):
        for key, vals in p["by_feature"].items():
            parts = [f"{_VALUE_TITLE.get(v, v)} {d['acc']*100:.0f}% (n={d['n']})"
                     for v, d in vals.items()]
            st.markdown(f"**{_FEATURE_TITLE.get(key, key)}** — " + " · ".join(parts))


def _shared_pool():
    own_n, seed_n, partner_n = trainer.pool_sources()
    with st.expander("Shared pool — learn from another trader's reads"):
        st.caption("Pool your graded calls with a partner's so the bot learns "
                   "from more decisions. The trusted set is weighted higher. "
                   "Everything stays on this computer — you share by file (e.g. "
                   "on a USB stick), nothing is uploaded.")
        text = trainer.calls_for_sharing()
        st.download_button(
            "⬇ Export my reads (to share)", data=text or "",
            file_name="scout_reads.jsonl", mime="text/plain",
            disabled=not text,
            help="Saves your graded calls (just the read + outcome, no account "
                 "info) so another Scout can learn from them.")
        up = st.file_uploader("⬆ Add a partner's reads", type=["jsonl", "txt", "json"],
                              key="partner_upload")
        if up is not None and st.button("Import these reads"):
            import tempfile
            from pathlib import Path as _P
            tmp = _P(tempfile.gettempdir()) / "scout_partner_upload.jsonl"
            tmp.write_bytes(up.getvalue())
            try:
                n = trainer.import_partner_calls(str(tmp))
                st.success(f"Imported {n} reads — they now feed your pool "
                           "(at partner weight).")
                st.rerun()
            except Exception as exc:
                st.error(f"Couldn't read that file ({exc}).")
        if seed_n or partner_n:
            st.caption(f"Pool right now: your **{own_n}** + **{seed_n}** seed + "
                       f"**{partner_n}** partner reads.")


def render():
    ui.section("Trainer", "Blinded real charts with your full setup — call the "
               "direction, build the record. Teaches the system how you read.")
    remaining = len([s for s in trainer.pool() if s["id"] not in trainer.answered_ids()])

    if st.session_state.get("trainer_result"):
        _reveal_block(st.session_state["trainer_result"])
    else:
        snap = st.session_state.get("trainer_snap") or trainer.next_unanswered()
        if snap is None:
            st.info("You've gone through every chart in the pool. Generate a "
                    "fresh batch below to keep going.")
        else:
            st.session_state["trainer_snap"] = snap
            st.caption(f"Mystery chart · {remaining} left in this batch · "
                       "ticker and what happens next are hidden until you call it")
            _ask_block(snap)

    st.divider()
    _analytics()
    _patterns()
    _shared_pool()

    with st.expander("Add more charts to the pool"):
        st.caption("New practice charts also arrive automatically with **Scout "
                   "updates** (Links → Check for updates). To fetch your own here "
                   "you need your Alpaca data keys saved; it takes ~1–2 min.")
        n = st.number_input("How many", 5, 50, 15, step=5, key="gen_n")
        if st.button("Generate"):
            with st.spinner(f"Building {int(n)} blinded snapshots from real data…"):
                added = trainer.generate(int(n))
            st.success(f"Added {added} charts.")
            st.rerun()
