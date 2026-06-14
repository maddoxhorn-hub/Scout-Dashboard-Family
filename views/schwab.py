"""Schwab -- live accounts when connected, a clear path when not."""

import pandas as pd
import streamlit as st

import ui


def render(ctx):
    if ctx.schwab_error == "not_configured":
        ui.section("Schwab", "Personal account balances and positions, read-only")
        st.html(ui.pill("Waiting on Schwab API approval", "orange"))
        st.write("")
        ui.status_list([
            ("on", "1 · Developer account created", "developer.schwab.com"),
            ("on", "2 · App registered", 'Callback: https://127.0.0.1:8182'),
            ("wait", "3 · Approval", 'Check the portal until it says "Ready For Use"'),
            ("off", "4 · Paste App Key + Secret", "into config.py"),
            ("off", "5 · Log in once", "python schwab_login.py"),
        ])
        st.caption(
            'Schwab shows "Approved – Pending" first — that still means not '
            "approved. It usually flips to Ready For Use within a few days. "
            "Steps 4–5 take about two minutes once it does."
        )
        return

    if ctx.schwab_error == "no_token":
        ui.section("Schwab", "One step left")
        st.info(
            "Keys are in config.py — now log in once. In this folder, run:\n\n"
            "```\n.venv\\Scripts\\python.exe schwab_login.py\n```\n\n"
            "A browser opens; sign in with your regular Schwab credentials "
            "and approve. Then refresh this page."
        )
        return

    if ctx.schwab_error:
        ui.section("Schwab")
        st.error(ctx.schwab_error)
        st.caption(
            "Schwab logins expire about every 7 days. Running "
            "`.venv\\Scripts\\python.exe schwab_login.py` again fixes most failures."
        )
        return

    if not ctx.schwab_accounts:
        ui.section("Schwab")
        st.info(
            "Connected, but Schwab returned no accounts. Re-run "
            "`schwab_login.py` and make sure you tick the account(s) on the "
            "consent screen."
        )
        return

    ui.section("Schwab accounts", "Live balances and positions, read-only")
    for acct in ctx.schwab_accounts:
        st.html(
            f'<div class="sec"><h3>Account {acct["label"]} '
            f'{ui.pill(acct["type"] or "account", "blue")}</h3></div>'
        )
        ui.cards([
            ui.card("Account value", ui.money(acct["liquidation_value"])),
            ui.card("Cash", ui.money(acct["cash"])),
            ui.card("Buying power", ui.money(acct["buying_power"])),
            ui.card(
                "Day P&L (positions)",
                ui.money(acct["day_pl_positions"], signed=True),
                tone=ui.tone_of(acct["day_pl_positions"]),
            ),
        ])
        if acct["positions"]:
            st.dataframe(
                pd.DataFrame(acct["positions"]), hide_index=True, width="stretch"
            )
        else:
            st.caption("No open positions in this account.")
