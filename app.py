"""
Scout -- a personal command center for trading and money.

Read-only by design: the Google credentials are opened view-only, only
Schwab's read endpoints are called, and bank data arrives via CSV files
parsed locally. Nothing here can place an order or move a dollar.

Run with:
    streamlit run app.py
or double-click "Scout Dashboard" on the desktop.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

import analytics
import config
import data_sources
import ui

_ICON = Path(__file__).parent / "assets" / "icon.png"
st.set_page_config(
    page_title="Scout",
    page_icon=str(_ICON) if _ICON.exists() else "🔭",
    layout="wide",
    initial_sidebar_state="collapsed",
)
ui.inject_css()


# ----------------------------------------------------------------------
# Cached loaders (Refresh clears these)
# ----------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def start_downloads_watcher():
    """One background thread per server: imports bank CSVs the moment
    they land in Downloads and closes the pickup window when done."""
    import threading

    from budget import downloads

    thread = threading.Thread(
        target=downloads.watch_forever, daemon=True, name="scout-downloads"
    )
    thread.start()
    return thread


start_downloads_watcher()


@st.cache_resource(show_spinner=False)
def start_market_watcher():
    """One background thread per server: polls watched tickers once a
    minute while the market is open and trips reversal alert wires."""
    import threading

    from market import watcher

    thread = threading.Thread(
        target=watcher.watch_forever, daemon=True, name="scout-markets"
    )
    thread.start()
    return thread


start_market_watcher()


@st.fragment(run_every="10s")
def live_data_pulse():
    """Refresh the page when the watcher imports new bank data, so files
    visibly turn into numbers without anyone pressing anything. Bank CSVs
    arrive minutes apart, so 10s is plenty — and it only runs on the pages
    that show bank data (see the gated call after the nav)."""
    from budget import store

    signal = store.change_signal()
    previous = st.session_state.get("_data_signal")
    st.session_state["_data_signal"] = signal
    if previous is not None and signal != previous:
        st.session_state["_new_data"] = True
        st.rerun(scope="app")


@st.cache_data(ttl=60, show_spinner=False)
def get_sheet_rows():
    return data_sources.load_trade_log()


@st.cache_data(ttl=120, show_spinner=False)
def get_schwab():
    return data_sources.load_schwab_accounts()


def load_context() -> SimpleNamespace:
    sheet_error = None
    trades = analytics.prepare_trades(None)
    try:
        trades = analytics.prepare_trades(get_sheet_rows())
    except FileNotFoundError:
        sheet_error = (
            f"Can't find {config.GOOGLE_CREDS_FILE} in this folder. Copy the "
            "service-account file from the bot folder (SETUP.md, Part 1)."
        )
    except Exception as exc:
        name = type(exc).__name__
        if "SpreadsheetNotFound" in name or "PERMISSION_DENIED" in str(exc) or "404" in str(exc):
            sheet_error = (
                "The service account can't open the trade log (SHEET_ID in "
                "config.py). Check the ID matches the bot's config.py and "
                "that the sheet is shared with the service-account email "
                "from credentials.json."
            )
        else:
            sheet_error = f"Couldn't read the trade log: {exc}"

    stats = analytics.headline_stats(trades) if sheet_error is None else {"n_closed": 0}
    schwab_accounts, schwab_error = get_schwab()
    schwab_total = (
        sum(a["liquidation_value"] or 0 for a in schwab_accounts)
        if schwab_accounts else None
    )
    return SimpleNamespace(
        trades=trades,
        stats=stats,
        sheet_error=sheet_error,
        schwab_accounts=schwab_accounts,
        schwab_error=schwab_error,
        schwab_total=schwab_total,
        bot_equity=config.STARTING_CAPITAL + stats.get("total_pnl", 0.0),
    )


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------

now = datetime.now()
head_left, head_right = st.columns([6, 1], vertical_alignment="center")
with head_left:
    st.html(
        '<div class="scout-wordmark">Scout</div>'
        f'<div class="scout-sub">{now:%A, %B} {now.day} · read-only · '
        f'never moves real money</div>'
    )
with head_right:
    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

st.write("")

if st.session_state.pop("_new_data", False):
    st.toast("New bank data imported", icon="✅")

import updater  # noqa: E402


@st.cache_data(ttl=21600, show_spinner=False)
def _update_banner_status():
    """One quiet update check per session. Short timeout, never raises,
    so a slow or missing network can't delay the dashboard."""
    try:
        return updater.check(timeout=6)
    except Exception:
        return None


PAGES = ["Overview", "Trading", "Markets", "Scans", "Trainer", "Schwab", "Budget", "Links"]
# Deep link support: http://localhost:8501/?page=Budget opens that page.
_requested = st.query_params.get("page", "Overview")
_default = _requested if _requested in PAGES else "Overview"
page = st.segmented_control(
    "Navigate", PAGES, default=_default,
    label_visibility="collapsed", key="nav",
) or _default
st.write("")

# Poll for freshly-imported bank data only on the pages that show it, so
# Markets/Scans/Trainer aren't re-running every few seconds for nothing.
if page in ("Overview", "Budget"):
    live_data_pulse()

# Gentle nudge when a newer Scout is published (the Links tab does the work).
if page != "Links":
    _upd = _update_banner_status()
    if _upd and _upd.get("available"):
        st.warning(
            f"🔄 A newer Scout (**{_upd['latest']}**) is ready. "
            "Open the **Links** tab and press **Update now**."
        )


# ----------------------------------------------------------------------
# Route
# ----------------------------------------------------------------------

from views import budget as budget_view  # noqa: E402
from views import links, markets, overview, scans, schwab, trading, trainer  # noqa: E402

if page == "Overview":
    overview.render(load_context())
elif page == "Trading":
    trading.render(load_context())
elif page == "Markets":
    markets.render()
elif page == "Scans":
    scans.render()
elif page == "Trainer":
    trainer.render()
elif page == "Schwab":
    schwab.render(load_context())
elif page == "Budget":
    budget_view.render()
elif page == "Links":
    links.render()

st.html(
    f'<div style="margin-top:48px;color:#A8A8AD;font-size:12px;font-weight:500;">'
    f"Scout · data stays on this machine · loaded {now:%I:%M %p}</div>"
)
