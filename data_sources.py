"""
Read-only data feeds for the dashboard.

Two sources live here:
  1. The bot's Google Sheet trade log (via the service account).
  2. Your personal Schwab account(s) (via the official Trader API).

Nothing in this file can place, change, or cancel an order. The Google
credentials are authorized with read-only scopes, and only read endpoints
of the Schwab API are ever called.
"""

from pathlib import Path

import pandas as pd

import config

# Read-only scopes: even though the service account has edit rights on the
# sheet, THIS app deliberately asks Google for view-only access.
READONLY_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ----------------------------------------------------------------------
# Source 1: the bot's trade log
# ----------------------------------------------------------------------

def _trade_log_worksheet(spreadsheet):
    """Locate the tab the bots append trades to.

    Prefer the tab named TRADE_LOG_TAB. If it was renamed, fall back to
    the first tab whose header row matches the bot's log -- skipping the
    Shadow tab, which holds shadow-mode (no real orders) rows.
    """
    import gspread

    try:
        return spreadsheet.worksheet(config.TRADE_LOG_TAB)
    except gspread.exceptions.WorksheetNotFound:
        pass
    for ws in spreadsheet.worksheets():
        if ws.title == "Shadow":
            continue
        if ws.row_values(1)[:2] == ["Timestamp", "Ticker"]:
            return ws
    raise RuntimeError(
        f'No tab named "{config.TRADE_LOG_TAB}" and no tab with the '
        "bot's log headers (Timestamp, Ticker, ...) was found in the sheet."
    )


def load_trade_log() -> pd.DataFrame:
    """Return every row of the bot's log as a DataFrame.

    Reads the trade-log tab of the sheet -- the same one logger.py writes
    to. Raises an exception with a readable message if anything goes
    wrong; the app catches it and shows a fix-it hint.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        config.GOOGLE_CREDS_FILE, scopes=READONLY_SCOPES
    )
    client = gspread.authorize(creds)
    worksheet = _trade_log_worksheet(client.open_by_key(config.SHEET_ID))
    records = worksheet.get_all_records()
    return pd.DataFrame(records)


# ----------------------------------------------------------------------
# Source 2: Schwab accounts (balances + positions)
# ----------------------------------------------------------------------

def schwab_setup_state() -> str:
    """Where the user is in Schwab setup: 'not_configured', 'no_token', or 'ready'."""
    if "PASTE_YOUR" in config.SCHWAB_API_KEY or "PASTE_YOUR" in config.SCHWAB_APP_SECRET:
        return "not_configured"
    if not Path(config.SCHWAB_TOKEN_PATH).exists():
        return "no_token"
    return "ready"


def _schwab_client():
    """Build an authenticated Schwab client from the saved token file."""
    from schwab.auth import client_from_token_file

    return client_from_token_file(
        config.SCHWAB_TOKEN_PATH,
        config.SCHWAB_API_KEY,
        config.SCHWAB_APP_SECRET,
    )


def load_schwab_accounts():
    """Fetch balances and positions for every linked Schwab account.

    Returns (accounts, error):
      accounts -- list of plain dicts (safe to cache / display)
      error    -- None on success, otherwise one of:
                  'not_configured', 'no_token', or 'failed: <detail>'
    """
    state = schwab_setup_state()
    if state != "ready":
        return [], state

    try:
        client = _schwab_client()
    except Exception as exc:  # bad/expired token, corrupted file, etc.
        return [], f"failed: could not load the saved login ({exc})"

    try:
        try:
            resp = client.get_accounts(fields=client.Account.Fields.POSITIONS)
        except (AttributeError, TypeError):
            resp = client.get_accounts()
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        return [], f"failed: Schwab request error ({exc})"

    accounts = []
    for item in raw if isinstance(raw, list) else []:
        acct = item.get("securitiesAccount", {}) if isinstance(item, dict) else {}
        balances = acct.get("currentBalances", {}) or {}

        positions = []
        day_pl_total = 0.0
        for pos in acct.get("positions", []) or []:
            instrument = pos.get("instrument", {}) or {}
            qty = float(pos.get("longQuantity") or 0) - float(pos.get("shortQuantity") or 0)
            day_pl = float(pos.get("currentDayProfitLoss") or 0)
            day_pl_total += day_pl
            positions.append(
                {
                    "Symbol": instrument.get("symbol", "?"),
                    "Type": instrument.get("assetType", ""),
                    "Qty": qty,
                    "Avg price": pos.get("averagePrice"),
                    "Market value": pos.get("marketValue"),
                    "Day P&L": day_pl,
                }
            )

        number = str(acct.get("accountNumber", ""))
        accounts.append(
            {
                "label": f"\u00b7\u00b7\u00b7{number[-4:]}" if number else "account",
                "type": acct.get("type", ""),
                "liquidation_value": balances.get("liquidationValue"),
                "cash": balances.get(
                    "cashBalance", balances.get("cashAvailableForTrading")
                ),
                "buying_power": balances.get(
                    "buyingPower", balances.get("cashAvailableForTrading")
                ),
                "day_pl_positions": day_pl_total,
                "positions": positions,
            }
        )

    return accounts, None
