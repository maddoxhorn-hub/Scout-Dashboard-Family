"""
Scout's design system.

One place for the look: CSS, typography, card builders, and the chart
style. Views compose these helpers; none of them touch data.
"""

import html as _html

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------
# Palette
# ----------------------------------------------------------------------

INK = "#1D1D1F"          # primary text
INK_SOFT = "#6E6E73"     # secondary text
INK_FAINT = "#86868B"    # captions
LINE = "#E8E8ED"         # hairline borders
CANVAS = "#F5F5F7"       # page background
CARD = "#FFFFFF"
BLUE = "#0071E3"
GREEN = "#34C759"
RED = "#FF3B30"
ORANGE = "#FF9500"

CHART_SERIES = [
    "#0A84FF", "#34C759", "#FF9F0A", "#FF375F",
    "#BF5AF2", "#64D2FF", "#FFD60A", "#FF6482",
    "#30D158", "#86868B",
]

FONT_STACK = (
    "Inter, -apple-system, BlinkMacSystemFont, 'SF Pro Display', "
    "'Segoe UI', Roboto, sans-serif"
)


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------

def money(value, signed=False, decimals=2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}${abs(value):,.{decimals}f}"


def pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def tone_of(value) -> str:
    """CSS tone class for a signed number."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == 0:
        return "neutral"
    return "good" if value > 0 else "bad"


# ----------------------------------------------------------------------
# Global CSS
# ----------------------------------------------------------------------

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ---- canvas + type ------------------------------------------------ */
html, body, [data-testid="stAppViewContainer"] {{
    font-family: {FONT_STACK};
    color: {INK};
}}
[data-testid="stAppViewContainer"] {{ background: {CANVAS}; }}

/* hide Streamlit chrome: header bar, toolbar, footer, sidebar */
[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"],
#MainMenu, footer,
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{
    display: none !important;
}}

/* main column */
.block-container, [data-testid="stMainBlockContainer"] {{
    max-width: 1240px;
    padding: 1.6rem 2.2rem 4rem 2.2rem;
}}

h1, h2, h3 {{ letter-spacing: -0.02em; }}
a {{ text-decoration: none; }}

/* ---- wordmark header ---------------------------------------------- */
.scout-wordmark {{
    font-size: 34px; font-weight: 800; letter-spacing: -0.035em;
    color: {INK}; line-height: 1.1; margin: 0;
}}
.scout-sub {{
    color: {INK_FAINT}; font-size: 14px; font-weight: 500;
    margin-top: 2px;
}}

/* ---- segmented control (st.segmented_control) ---------------------- */
[data-testid="stButtonGroup"] {{
    background: #E9E9EB;
    border-radius: 12px;
    padding: 3px;
    display: inline-flex;
    gap: 2px;
    flex-wrap: nowrap;
    border: none;
    width: auto;
}}
[data-testid="stButtonGroup"] button {{
    border: none !important;
    background: transparent;
    border-radius: 9.5px !important;
    padding: 7px 20px !important;
    margin: 0 !important;
    cursor: pointer;
    transition: background .15s ease, box-shadow .15s ease;
    box-shadow: none;
    min-height: 0;
}}
[data-testid="stButtonGroup"] button p {{
    font-size: 14px !important; font-weight: 600 !important; color: {INK_SOFT};
    letter-spacing: -0.01em;
}}
[data-testid="stButtonGroup"] button:hover p {{ color: {INK}; }}
[data-testid="stButtonGroup"] button[data-testid="stBaseButton-segmented_controlActive"] {{
    background: #FFFFFF !important;
    box-shadow: 0 1px 4px rgba(0,0,0,.10) !important;
}}
[data-testid="stButtonGroup"] button[data-testid="stBaseButton-segmented_controlActive"] p {{
    color: {INK} !important;
}}

/* ---- metric cards -------------------------------------------------- */
.cards {{
    display: grid;
    gap: 14px;
    margin: 4px 0 10px 0;
}}
@media (max-width: 980px) {{
    .cards {{ grid-template-columns: repeat(2, 1fr) !important; }}
}}
.card {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 16px;
    padding: 18px 20px 16px 20px;
}}
.card .k-label {{
    font-size: 13px; font-weight: 600; color: {INK_SOFT};
    margin-bottom: 6px; letter-spacing: -0.01em;
}}
.card .k-info {{ color: #C7C7CC; font-size: 11px; cursor: help; }}
.card .k-value {{
    font-size: 28px; font-weight: 700; letter-spacing: -0.025em;
    font-variant-numeric: tabular-nums; line-height: 1.15;
}}
.card .k-note {{
    font-size: 12.5px; color: {INK_FAINT}; margin-top: 5px;
    font-weight: 500;
}}
.k-value.good, .k-note.good {{ color: {GREEN}; }}
.k-value.bad, .k-note.bad {{ color: {RED}; }}
.k-value.neutral {{ color: {INK}; }}
.k-value.dim {{ color: {INK_FAINT}; font-weight: 600; }}

/* ---- section headings ---------------------------------------------- */
.sec {{ margin: 26px 0 10px 0; }}
.sec h3 {{
    font-size: 20px; font-weight: 700; margin: 0; color: {INK};
}}
.sec p {{
    font-size: 13.5px; color: {INK_FAINT}; margin: 3px 0 0 0; font-weight: 500;
}}

/* ---- status list (Apple settings style) ----------------------------- */
.statlist {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 16px;
    overflow: hidden;
}}
.statrow {{
    display: flex; align-items: center; gap: 12px;
    padding: 14px 18px; border-bottom: 1px solid #F2F2F4;
    font-size: 14.5px; font-weight: 500;
}}
.statrow:last-child {{ border-bottom: none; }}
.statrow .dot {{
    width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto;
}}
.dot.on {{ background: {GREEN}; }}
.dot.wait {{ background: {ORANGE}; }}
.dot.off {{ background: #C7C7CC; }}
.statrow .detail {{ margin-left: auto; color: {INK_FAINT}; font-size: 13.5px; text-align: right; }}

/* ---- merchant / simple list rows ----------------------------------- */
.rowline {{
    display: flex; align-items: baseline; gap: 10px;
    padding: 10px 2px; border-bottom: 1px solid #F2F2F4;
    font-size: 14px;
}}
.rowline:last-child {{ border-bottom: none; }}
.rowline .amt {{ margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 600; }}

/* ---- quick-link cards ----------------------------------------------- */
.linkgrid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(225px, 1fr));
    gap: 12px;
}}
a.linkcard {{
    display: block; background: {CARD}; border: 1px solid {LINE};
    border-radius: 14px; padding: 15px 17px;
    transition: transform .12s ease, box-shadow .12s ease;
}}
a.linkcard:hover {{
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(0,0,0,.07);
}}
a.linkcard .t {{ font-size: 14.5px; font-weight: 650; color: {INK}; }}
a.linkcard .d {{ font-size: 12.5px; color: {INK_FAINT}; margin-top: 3px; font-weight: 500; }}
a.linkcard .arrow {{ float: right; color: #C7C7CC; font-weight: 600; }}

/* ---- pills ----------------------------------------------------------- */
.pill {{
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 600;
}}
.pill.blue {{ background: #E8F1FD; color: {BLUE}; }}
.pill.orange {{ background: #FFF3E0; color: #C77700; }}
.pill.green {{ background: #E9F9EE; color: #1E8E3E; }}
.pill.gray {{ background: #EFEFF1; color: {INK_SOFT}; }}
.pill.red {{ background: #FDEBEA; color: #D70015; }}

/* ---- scan watchlist cards -------------------------------------------- */
.watchgrid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 14px;
}}
@media (max-width: 980px) {{
    .watchgrid {{ grid-template-columns: 1fr; }}
}}
.watchcard {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 16px;
    padding: 16px 18px 14px 18px;
}}
.watchcard .w-top {{
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}}
.watchcard .w-sym {{
    font-size: 19px; font-weight: 700; letter-spacing: -0.02em;
}}
.watchcard .w-move {{
    margin-left: auto; font-weight: 700; font-size: 15px;
    font-variant-numeric: tabular-nums;
}}
.w-move.good {{ color: {GREEN}; }}
.w-move.bad {{ color: {RED}; }}
.w-move.neutral {{ color: {INK_FAINT}; }}
.watchcard .w-prices {{
    font-size: 13px; color: {INK_SOFT}; font-weight: 500; margin-top: 5px;
    font-variant-numeric: tabular-nums;
}}
.watchcard .w-thesis {{
    font-size: 13.5px; color: {INK}; margin-top: 9px; line-height: 1.45;
}}
.watchcard .w-trig {{
    font-size: 12.5px; color: {INK_FAINT}; margin-top: 8px; font-weight: 500;
    line-height: 1.4;
}}

/* ---- check-log timeline ----------------------------------------------- */
.timeline {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 16px;
    padding: 18px 20px 6px 20px;
}}
.tl-item {{
    position: relative; padding: 0 0 16px 26px;
    border-left: 2px solid #F0F0F2; margin-left: 5px;
}}
.tl-item:last-child {{ border-left-color: transparent; }}
.tl-item::before {{
    content: ""; position: absolute; left: -6px; top: 3px;
    width: 10px; height: 10px; border-radius: 50%;
    background: #C7C7CC; border: 2px solid {CARD};
}}
.tl-item.alerted::before {{ background: {ORANGE}; }}
.tl-time {{
    font-size: 12px; font-weight: 600; color: {INK_FAINT};
    font-variant-numeric: tabular-nums;
}}
.tl-summary {{
    font-size: 14px; font-weight: 500; color: {INK}; margin-top: 2px;
    line-height: 1.45;
}}
.tl-alert {{ font-size: 13px; font-weight: 600; color: #C77700; margin-top: 4px; }}

/* ---- Streamlit widget restyling -------------------------------------- */
.stButton button, .stDownloadButton button, [data-testid="stPopoverButton"] {{
    border-radius: 10px !important;
    border: 1px solid {LINE} !important;
    background: {CARD};
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    color: {INK} !important;
}}
.stButton button:hover, [data-testid="stPopoverButton"]:hover {{
    border-color: #C7C7CC !important;
    color: {INK} !important;
}}
.stButton button[kind="primary"] {{
    background: {BLUE} !important; border-color: {BLUE} !important;
    color: #fff !important;
}}
.stButton button[kind="primary"]:hover {{ background: #0077ED !important; }}

[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {CARD};
    border: 1px solid {LINE} !important;
    border-radius: 16px !important;
    padding: 6px 10px;
}}

[data-testid="stExpander"] {{
    background: {CARD};
    border: 1px solid {LINE} !important;
    border-radius: 14px !important;
}}
[data-testid="stExpander"] summary {{ font-weight: 600; font-size: 14.5px; }}
[data-testid="stExpander"] details {{ border: none !important; }}

[data-testid="stAlertContainer"] {{
    border-radius: 14px;
    font-size: 14px;
}}

[data-testid="stFileUploaderDropzone"] {{
    background: #FAFAFC;
    border: 1.5px dashed #D2D2D7;
    border-radius: 14px;
}}

[data-testid="stWidgetLabel"] p {{
    font-size: 13px; font-weight: 600; color: {INK_SOFT};
}}

.stSelectbox [data-baseweb="select"] > div,
.stNumberInput input, .stTextInput input, .stDateInput input {{
    border-radius: 10px !important;
    border-color: {LINE} !important;
    background: {CARD} !important;
    font-weight: 500;
}}

[data-testid="stMetric"] {{
    background: {CARD}; border: 1px solid {LINE};
    border-radius: 16px; padding: 16px 20px;
}}

hr {{ border-color: {LINE}; }}
</style>
"""


def inject_css():
    st.html(_CSS)


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------

def _esc(text) -> str:
    return _html.escape(str(text))


def card(label, value, note=None, tone="neutral", note_tone=None, dim=False,
         help=None) -> str:
    """One metric card. Returns HTML; combine via cards(). `help` adds a
    plain-English hover explanation (and a small ⓘ) on the label, so jargon
    like 'Profit factor' can explain itself to a first-time user."""
    value_cls = "dim" if dim else tone
    note_html = (
        f'<div class="k-note {note_tone or ""}">{_esc(note)}</div>' if note else ""
    )
    if help:
        label_html = (f'<div class="k-label" title="{_esc(help)}">{_esc(label)} '
                      f'<span class="k-info" title="{_esc(help)}">ⓘ</span></div>')
    else:
        label_html = f'<div class="k-label">{_esc(label)}</div>'
    return (
        f'<div class="card">{label_html}'
        f'<div class="k-value {value_cls}">{_esc(value)}</div>{note_html}</div>'
    )


def cards(items):
    """Render a responsive row of metric cards. items = list of card() html."""
    n = max(1, min(len(items), 4))
    st.html(
        f'<div class="cards" style="grid-template-columns: repeat({n}, 1fr);">'
        f'{"".join(items)}</div>'
    )


def section(title, caption=None):
    cap = f"<p>{_esc(caption)}</p>" if caption else ""
    st.html(f'<div class="sec"><h3>{_esc(title)}</h3>{cap}</div>')


def status_list(rows):
    """rows = [(state, label, detail)] where state is 'on'|'wait'|'off'."""
    body = "".join(
        f'<div class="statrow"><span class="dot {state}"></span>'
        f"<span>{_esc(label)}</span>"
        f'<span class="detail">{_esc(detail)}</span></div>'
        for state, label, detail in rows
    )
    st.html(f'<div class="statlist">{body}</div>')


def row_list(rows):
    """rows = [(label, amount_html_or_text)] — simple Apple list."""
    body = "".join(
        f'<div class="rowline"><span>{_esc(label)}</span>'
        f'<span class="amt">{amount}</span></div>'
        for label, amount in rows
    )
    st.html(f"<div>{body}</div>")


def link_grid(links):
    """links = [(title, url, description)] — opens in a new tab."""
    cells = "".join(
        f'<a class="linkcard" href="{_esc(url)}" target="_blank" rel="noopener">'
        f'<span class="arrow">›</span><div class="t">{_esc(title)}</div>'
        f'<div class="d">{_esc(desc)}</div></a>'
        for title, url, desc in links
    )
    st.html(f'<div class="linkgrid">{cells}</div>')


def pill(text, color="gray") -> str:
    return f'<span class="pill {color}">{_esc(text)}</span>'


def watch_card(symbol, badges, price_line, thesis, triggers=None,
               move=None, move_tone="neutral") -> str:
    """One scan watchlist card. badges = list of pill() html; combine
    via watch_grid(). move is the since-entry change, toned by tone_of."""
    move_html = (
        f'<span class="w-move {move_tone}">{_esc(move)}</span>' if move else ""
    )
    trig_html = f'<div class="w-trig">{_esc(triggers)}</div>' if triggers else ""
    return (
        f'<div class="watchcard"><div class="w-top">'
        f'<span class="w-sym">{_esc(symbol)}</span>{"".join(badges)}{move_html}</div>'
        f'<div class="w-prices">{_esc(price_line)}</div>'
        f'<div class="w-thesis">{_esc(thesis)}</div>{trig_html}</div>'
    )


def watch_grid(items):
    """Render watchlist cards two-up. items = list of watch_card() html."""
    st.html(f'<div class="watchgrid">{"".join(items)}</div>')


def timeline(events):
    """events = [(time, summary, alerts)] — vertical check-log timeline.
    Entries with alerts get an orange dot."""
    body = "".join(
        f'<div class="tl-item{" alerted" if alerts else ""}">'
        f'<div class="tl-time">{_esc(time)}</div>'
        f'<div class="tl-summary">{_esc(summary)}</div>'
        + "".join(f'<div class="tl-alert">⚠ {_esc(a)}</div>' for a in alerts)
        + "</div>"
        for time, summary, alerts in events
    )
    st.html(f'<div class="timeline">{body}</div>')


# ----------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------

def style_fig(fig, height=360, legend=True):
    """Apply the house chart style to a plotly figure."""
    fig.update_layout(
        height=height,
        margin=dict(l=6, r=6, t=12, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, size=12.5, color=INK_FAINT),
        xaxis=dict(showgrid=False, zeroline=False, showline=False, ticks=""),
        yaxis=dict(gridcolor="#F0F0F2", zeroline=False, showline=False, ticks=""),
        colorway=CHART_SERIES,
        hoverlabel=dict(
            bgcolor=INK, font=dict(color="#fff", family=FONT_STACK, size=12.5),
            bordercolor=INK,
        ),
        showlegend=legend,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=12.5),
        ),
    )
    return fig


PLOTLY_CONFIG = {"displayModeBar": False}
