"""Budget -- spending across Discover, Amex, and KeyBank.

Bank CSVs go in, a clean monthly picture comes out. Everything stays in
data/budget.db on this machine.
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import ui
from budget import downloads, importers, plaid_sync, store

# The bank-linking helper. Launched with the same Python that runs Scout, so
# it works the same on Windows and on a Mac (no .bat needed).
_LINK_SCRIPT = Path(__file__).resolve().parent.parent / "plaid_link.py"


def render():
    txns = store.transactions_cached()
    plaid_state = plaid_sync.setup_state()

    # A sync from the previous run wants its toast shown after the rerun.
    if "plaid_sync_msg" in st.session_state:
        st.toast(st.session_state.pop("plaid_sync_msg"))

    if txns.empty:
        ui.section("Budget", "Discover · Amex · KeyBank — all local, nothing uploaded anywhere")
        st.info(
            "No transactions yet. Press **Get bank files** — your banks "
            "open in their own window; download the transactions CSV at "
            "each one and Scout imports the files the moment they land "
            "in Downloads. You can close the bank window once each file "
            "finishes downloading."
        )
        _get_files_button(primary=True)
        if plaid_state == "ready":
            _sync_button()
        _plaid_panel()
        _import_panel()
        return

    # ------------------------------------------------------------------ month picker
    months = sorted(txns["date"].dt.to_period("M").unique(), reverse=True)
    labels = {m: m.strftime("%B %Y") for m in months}
    head_l, head_m, head_r = st.columns([4.1, 1.1, 1.4], vertical_alignment="bottom")
    with head_m:
        if plaid_state == "ready":
            _sync_button()
        else:
            _get_files_button()
    with head_l:
        ui.section("Budget", "All local, nothing uploaded · spending excludes "
                   "card payments and transfers, so nothing double-counts")
    with head_r:
        chosen = st.selectbox(
            "Month", months, format_func=lambda m: labels[m],
            label_visibility="collapsed",
        )
    _freshness_caption()

    month_df = txns[txns["date"].dt.to_period("M") == chosen]
    spend_mask = (month_df["amount"] < 0) & ~month_df["category"].isin(store.NON_SPENDING)
    spending = -month_df.loc[spend_mask, "amount"].sum()
    income = month_df.loc[
        (month_df["amount"] > 0) & (month_df["category"] != "Transfers & Payments"),
        "amount",
    ].sum()
    net = income - spending

    today = date.today()
    if chosen == pd.Period(today, freq="M"):
        days = max(today.day, 1)
        pace_note = f"{ui.money(spending / days)} / day so far"
    else:
        days = chosen.days_in_month
        pace_note = f"{ui.money(spending / days)} / day"

    ui.cards([
        ui.card("Spent", ui.money(spending), note=pace_note),
        ui.card("Income", ui.money(income)),
        ui.card("Net", ui.money(net, signed=True), tone=ui.tone_of(net),
                note="Income minus spending"),
        ui.card("Transactions", f"{len(month_df):,}",
                note=f"across {month_df['account'].nunique()} account(s)"),
    ])

    # ------------------------------------------------------------------ charts
    col_donut, col_trend = st.columns([1, 1.4])

    by_cat = (
        -month_df.loc[spend_mask].groupby("category")["amount"].sum()
    ).sort_values(ascending=False)
    with col_donut:
        with st.container(border=True):
            st.caption(f"Where it went · {labels[chosen]}")
            if by_cat.empty:
                st.caption("No spending recorded this month.")
            else:
                donut = go.Figure(go.Pie(
                    labels=by_cat.index, values=by_cat.values,
                    hole=0.62, sort=False,
                    textinfo="percent", textposition="inside",
                    insidetextorientation="radial",
                    hovertemplate="%{label}: %{value:$,.0f} (%{percent})<extra></extra>",
                ))
                donut.add_annotation(
                    text=f"<b>{ui.money(spending, decimals=0)}</b><br>"
                         f"<span style='font-size:12px;color:{ui.INK_FAINT}'>"
                         f"{labels[chosen]}</span>",
                    showarrow=False, font=dict(size=19, color=ui.INK),
                )
                ui.style_fig(donut, height=290)
                donut.update_layout(legend=dict(orientation="v", y=0.5, x=1.02))
                st.plotly_chart(donut, config=ui.PLOTLY_CONFIG)

    with col_trend:
        with st.container(border=True):
            st.caption("Monthly spending · last 12 months")
            all_spend = txns[
                (txns["amount"] < 0) & ~txns["category"].isin(store.NON_SPENDING)
            ].copy()
            trend = (
                -all_spend.groupby(all_spend["date"].dt.to_period("M"))["amount"]
                .sum().sort_index().tail(12)
            )
            bars = go.Figure(go.Bar(
                x=[p.strftime("%b %y") for p in trend.index],
                y=trend.values,
                marker=dict(
                    color=[
                        ui.BLUE if p == chosen else "#D8D8DC" for p in trend.index
                    ],
                    cornerradius=6,
                ),
                hovertemplate="%{x}: %{y:$,.0f}<extra></extra>",
            ))
            ui.style_fig(bars, height=290, legend=False)
            bars.update_yaxes(tickprefix="$")
            st.plotly_chart(bars, config=ui.PLOTLY_CONFIG)

    # ------------------------------------------------------------------ top merchants
    if not by_cat.empty:
        ui.section("Top merchants", labels[chosen])
        with st.container(border=True):
            top = (
                (-month_df.loc[spend_mask]
                 .groupby(month_df["description"].str.slice(0, 42))["amount"]
                 .sum())
                .sort_values(ascending=False).head(6)
            )
            ui.row_list([
                (name, ui.money(amount)) for name, amount in top.items()
            ])

    # ------------------------------------------------------------------ transactions
    ui.section("Transactions", "Fix a category here and Scout remembers it for that row")
    f1, f2, f3 = st.columns([1.2, 1.2, 2])
    with f1:
        acct_pick = st.multiselect(
            "Account", sorted(txns["account"].unique()), placeholder="All accounts",
        )
    with f2:
        cat_pick = st.multiselect("Category", store.CATEGORIES, placeholder="All categories")
    with f3:
        search = st.text_input("Search", placeholder="Search descriptions…")

    view = month_df.copy()
    if acct_pick:
        view = view[view["account"].isin(acct_pick)]
    if cat_pick:
        view = view[view["category"].isin(cat_pick)]
    if search.strip():
        view = view[view["description"].str.contains(search.strip(), case=False, regex=False)]

    edited = st.data_editor(
        view,
        hide_index=True,
        width="stretch",
        column_order=["date", "account", "description", "amount", "category"],
        disabled=["date", "account", "description", "amount"],
        column_config={
            "date": st.column_config.DateColumn("Date", format="MMM D"),
            "account": st.column_config.TextColumn("Account"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "amount": st.column_config.NumberColumn("Amount", format="dollar"),
            "category": st.column_config.SelectboxColumn(
                "Category", options=store.CATEGORIES, required=True,
            ),
        },
        key=f"txn_editor_{chosen}",
    )
    changed = edited[edited["category"] != view["category"]]
    if not changed.empty:
        for _, row in changed.iterrows():
            store.set_category(int(row["id"]), row["category"])
        st.toast(f"Updated {len(changed)} categor{'ies' if len(changed) > 1 else 'y'}")
        st.rerun()

    # ------------------------------------------------------------------ manage
    ui.section("Manage")
    _plaid_panel()
    _import_panel()
    _rules_panel()
    with st.expander("Where this data lives"):
        accounts = store.accounts_summary()
        st.dataframe(accounts, hide_index=True, width="stretch")
        st.caption(
            "Everything is stored in data/budget.db inside this folder — "
            "no cloud, no third party. Bank CSVs are deleted the moment "
            "their rows are saved here, so no plaintext files linger. "
            "Re-importing an overlapping range is always safe; duplicates "
            "are skipped automatically."
        )


# ----------------------------------------------------------------------
# Bank-file pickup
# ----------------------------------------------------------------------

def _get_files_button(primary=False):
    if st.button("Get bank files", type="primary" if primary else "secondary",
                 help="Open every bank's download page in its own window; "
                      "Scout imports the CSVs automatically as they land"):
        result = downloads.open_bank_pages(force=True)
        if result["opened"]:
            st.toast(
                "Banks opened in a new window — download the transactions "
                "CSV at each one and Scout imports them automatically. You "
                "can close the bank window when you're done."
            )
        else:
            st.toast("Couldn't open a browser window — check SETUP.md.")


def _freshness_caption():
    last = store.last_imports()
    parts = []
    for bank in config.BANK_ACCOUNTS:
        ts = last.get(bank)
        if ts is None:
            parts.append(f"{bank}: never")
            continue
        days = (date.today() - pd.to_datetime(ts).date()).days
        parts.append(
            f"{bank}: today" if days == 0
            else f"{bank}: {days} day{'s' if days != 1 else ''} ago"
        )
    st.caption("Files last received — " + " · ".join(parts))


# ----------------------------------------------------------------------
# Plaid
# ----------------------------------------------------------------------

def _sync_button(primary=False):
    if st.button("Sync", type="primary" if primary else "secondary",
                 help="Pull new transactions from every linked bank"):
        with st.spinner("Syncing from Plaid…"):
            results = plaid_sync.sync_all()
        errors = [r for r in results if r["error"]]
        added = sum(r["added"] for r in results)
        for r in errors:
            st.error(
                f"{r['account']}: {r['error']} — if the bank wants a fresh "
                "login, run plaid_link.py again for that bank."
            )
        if not errors:
            st.session_state["plaid_sync_msg"] = (
                f"Synced — {added} new transaction(s)" if added
                else "Synced — nothing new"
            )
            st.rerun()


def _keys_form(form_key):
    with st.form(form_key, border=False):
        client_id = st.text_input("Client ID", type="password")
        secret = st.text_input("Secret", type="password")
        if st.form_submit_button("Save keys", type="primary"):
            if not (client_id.strip() and secret.strip()):
                st.error("Both fields are needed.")
            else:
                with st.spinner("Checking the keys with Plaid…"):
                    try:
                        env = plaid_sync.validate_keys(client_id, secret)
                    except RuntimeError as exc:
                        env = None
                        st.error(
                            f"Plaid rejected these keys ({exc}). Re-copy "
                            "both from dashboard.plaid.com → Developers → "
                            "Keys and try again."
                        )
                if env:
                    plaid_sync.save_keys(client_id, secret, env)
                    st.toast(f"Keys verified with Plaid ({env}) and saved")
                    st.rerun()


def _link_bank_button(label="Link a bank"):
    if st.button(label):
        try:
            subprocess.Popen(
                [sys.executable, str(_LINK_SCRIPT)],
                cwd=str(_LINK_SCRIPT.parent),
            )
            st.toast(
                "A browser window is opening — pick the bank and log in "
                "there, then come back and press Sync."
            )
        except OSError as exc:
            st.error(f"Couldn't start the bank-linking helper ({exc}).")


def _plaid_panel(expanded=False):
    with st.expander("Plaid — live bank sync", expanded=expanded):
        state = plaid_sync.setup_state()
        if state == "not_configured":
            st.caption(
                "Paste your two Plaid keys below — they're at "
                "**dashboard.plaid.com → Developers → Keys**. Use the "
                "**production** secret (sandbox is Plaid's practice mode). "
                "They're saved into config.py on this machine and nowhere "
                "else."
            )
            _keys_form("plaid_keys")
            st.caption(
                "Then press **Link a bank** once per bank — a browser opens "
                "with Plaid's secure login. Your bank credentials go to "
                "Plaid, never to Scout; the saved tokens can only *read* "
                "transactions."
            )
        elif state == "no_items":
            if config.PLAID_ENV == "sandbox":
                st.warning(
                    "The saved keys are **sandbox** keys — Plaid's practice "
                    "mode, where only fake test banks exist. Real Discover, "
                    "Amex, and KeyBank logins need the **production** "
                    "secret. On **dashboard.plaid.com → Developers → "
                    "Keys**, look at the Production row: if a secret is "
                    "shown, copy it and save both keys again below. If it "
                    "says access hasn't been granted yet, request "
                    "production access on that page (Plaid approves it "
                    "like Schwab does) — CSV import works in the meantime."
                )
                _keys_form("plaid_keys_replace")
            else:
                st.caption(
                    "Keys are in place — now link each bank. Press the "
                    "button below (once per bank: Discover, Amex, KeyBank). "
                    "A browser opens with Plaid's secure flow — pick the "
                    "bank and log in there; your credentials go to Plaid, "
                    "never to Scout."
                )
                _link_bank_button()
        else:
            rows = []
            for item in plaid_sync.linked_items():
                last = item.get("last_sync")
                detail = (
                    f"last sync {last[:16].replace('T', ' ')}" if last
                    else "never synced"
                )
                rows.append(("on", item["account"], detail))
            ui.status_list(rows)
            _link_bank_button("Link another bank")
            st.caption(
                "Sync any time with the button up top. If a bank's login "
                "breaks, link it again here and it replaces the old one. "
                "Tokens live in data/plaid_tokens.json — local only."
            )


# ----------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------

def _import_panel(first_run=False):
    title = "Import bank CSVs"
    with st.expander(title, expanded=first_run):
        st.caption(
            "Where to download: "
            f"Discover — {importers.PROFILES['Discover']['hint']} · "
            f"Amex — {importers.PROFILES['Amex']['hint']} · "
            f"KeyBank — {importers.PROFILES['KeyBank']['hint']}"
        )
        files = st.file_uploader(
            "Drop bank files here",
            type=["csv", "pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        for f in files or []:
            data = f.getvalue()

            if f.name.lower().endswith(".pdf"):
                from budget import keybank_pdf

                try:
                    parsed = keybank_pdf.parse_statement(data)
                except ValueError as exc:
                    st.error(f"{f.name}: {exc}")
                    continue
                st.write(f"**{f.name}** — KeyBank statement")
                st.caption(
                    f"{len(parsed)} transactions · {parsed['date'].min()} → "
                    f"{parsed['date'].max()} · reconciled with the "
                    "statement's own balances"
                )
                if st.button(f"Import into KeyBank", key=f"import_{f.name}",
                             type="primary"):
                    added, skipped = store.add_transactions(parsed, "KeyBank")
                    st.toast(f"{f.name}: {added} added, {skipped} duplicates skipped")
                    st.rerun()
                continue

            try:
                sniff = pd.read_csv(__import__("io").BytesIO(data), nrows=1)
                detected = importers.detect_profile(f.name, sniff.columns)
            except Exception:
                detected = "Other (bank-style: negative = money out)"

            c1, c2 = st.columns([2, 1.4], vertical_alignment="center")
            with c1:
                st.write(f"**{f.name}**")
            with c2:
                profile = st.selectbox(
                    "Bank", list(importers.PROFILES),
                    index=list(importers.PROFILES).index(detected),
                    key=f"profile_{f.name}",
                    label_visibility="collapsed",
                )
            try:
                parsed = importers.parse_csv(data, profile)
            except ValueError as exc:
                st.error(f"{f.name}: {exc}")
                continue

            account = importers.PROFILES[profile]["account"] or "Other"
            total_out = -parsed.loc[parsed["amount"] < 0, "amount"].sum()
            st.caption(
                f"{len(parsed)} transactions · {parsed['date'].min()} → "
                f"{parsed['date'].max()} · {ui.money(total_out)} money out"
                + (f" · {parsed.attrs.get('dropped', 0)} unreadable row(s) skipped"
                   if parsed.attrs.get("dropped") else "")
            )
            if st.button(
                f"Import into {account}", key=f"import_{f.name}", type="primary",
            ):
                added, skipped = store.add_transactions(parsed, account)
                st.toast(f"{f.name}: {added} added, {skipped} duplicates skipped")
                st.rerun()


def _rules_panel():
    with st.expander("Category rules"):
        st.caption(
            "If a description contains the keyword, the transaction gets the "
            "category. Add your own rows; Save reapplies rules to everything."
        )
        rules = store.get_rules()
        edited = st.data_editor(
            rules,
            hide_index=True,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "keyword": st.column_config.TextColumn("Description contains"),
                "category": st.column_config.SelectboxColumn(
                    "Category", options=store.CATEGORIES, required=True,
                ),
            },
            key="rules_editor",
        )
        if st.button("Save rules & reapply", type="primary"):
            store.save_rules(edited)
            changed = store.recategorize_all()
            st.toast(f"Rules saved — {changed} transaction(s) recategorized")
            st.rerun()
