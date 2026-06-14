"""
Plaid -> Scout transaction sync.

One bank = one linked "item" in data/plaid_tokens.json (created by
plaid_link.py). sync_all() pulls whatever is new for every item via
Plaid's /transactions/sync, normalizes it to Scout's schema, and stores
it through the same path as CSV imports -- so dedupe, rules, and the
"transfers aren't spending" logic all behave identically.

Read-only by nature: the transactions product cannot move money, and the
access tokens never leave this machine.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from budget import store

_HOSTS = {
    "production": "https://production.plaid.com",
    "sandbox": "https://sandbox.plaid.com",
}

# Plaid personal-finance categories -> Scout categories.
# Detailed (most specific) entries win over primary ones.
_PFC_DETAILED = {
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "RENT_AND_UTILITIES_RENT": "Housing",
    "TRANSPORTATION_PUBLIC_TRANSIT": "Travel",
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": "Travel",
    "GENERAL_SERVICES_INSURANCE": "Insurance",
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT": "Transfers & Payments",
}
_PFC_PRIMARY = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfers & Payments",
    "TRANSFER_OUT": "Transfers & Payments",
    "LOAN_PAYMENTS": "Transfers & Payments",
    "BANK_FEES": "Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Housing",
    "RENT_AND_UTILITIES": "Utilities",
    "MEDICAL": "Health",
    "PERSONAL_CARE": "Health",
    "GENERAL_SERVICES": "Subscriptions",
    "TRANSPORTATION": "Gas & Auto",
    "TRAVEL": "Travel",
}

# Friendlier account labels for the institutions we expect.
_INSTITUTION_LABELS = {
    "american express": "Amex",
    "discover": "Discover",
    "keybank": "KeyBank",
    "key bank": "KeyBank",
}


# ----------------------------------------------------------------------
# Setup state + token file
# ----------------------------------------------------------------------

def keys_configured() -> bool:
    return not (
        "PASTE_YOUR" in config.PLAID_CLIENT_ID
        or "PASTE_YOUR" in config.PLAID_SECRET
    )


def validate_keys(client_id: str, secret: str) -> str:
    """Ask Plaid which environment accepts these keys.

    Returns 'production' or 'sandbox'. Raises RuntimeError with Plaid's
    production error message if neither accepts them.
    """
    import requests

    payload = {
        "client_id": client_id.strip().strip('"').strip("'"),
        "secret": secret.strip().strip('"').strip("'"),
        "client_name": "Scout",
        "user": {"client_user_id": "scout-keycheck"},
        "products": ["transactions"],
        "country_codes": ["US"],
        "language": "en",
    }
    first_error = None
    for env in ("production", "sandbox"):
        try:
            resp = requests.post(
                f"{_HOSTS[env]}/link/token/create", json=payload, timeout=30
            )
        except Exception as exc:
            raise RuntimeError(f"couldn't reach Plaid ({exc})")
        if resp.status_code == 200:
            return env
        if first_error is None:
            data = resp.json() if resp.content else {}
            first_error = data.get("error_message") or resp.text
    raise RuntimeError(first_error or "keys rejected")


def save_keys(client_id: str, secret: str, env: str = None):
    """Write Plaid keys (and optionally the environment) into config.py
    and reload config so the running app picks them up immediately."""
    import importlib
    import re

    path = Path(config.__file__)
    text = path.read_text(encoding="utf-8-sig")
    clean_id = client_id.strip().strip('"').strip("'")
    clean_secret = secret.strip().strip('"').strip("'")
    text = re.sub(r'PLAID_CLIENT_ID = "[^"]*"',
                  f'PLAID_CLIENT_ID = "{clean_id}"', text)
    text = re.sub(r'PLAID_SECRET = "[^"]*"',
                  f'PLAID_SECRET = "{clean_secret}"', text)
    if env:
        text = re.sub(r'PLAID_ENV = "[^"]*"',
                      f'PLAID_ENV = "{env}"', text)
    path.write_text(text, encoding="utf-8")
    importlib.reload(config)


def setup_state() -> str:
    """'not_configured' | 'no_items' | 'ready'"""
    if not keys_configured():
        return "not_configured"
    if not linked_items():
        return "no_items"
    return "ready"


def _tokens_path() -> Path:
    return Path(config.PLAID_TOKENS_PATH)


def linked_items() -> list:
    path = _tokens_path()
    if not path.exists():
        return []
    try:
        # utf-8-sig tolerates a BOM (Notepad and PowerShell add one)
        return json.loads(path.read_text(encoding="utf-8-sig")).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_item(institution: str, access_token: str, item_id: str):
    """Add (or replace) one linked bank. Called by plaid_link.py.

    Re-linking the same bank (e.g. after the bank forces a fresh login)
    replaces the old entry; already-synced transactions stay put and the
    plaid-id dedupe keeps the re-pull from double-counting.
    """
    label = account_label(institution)
    items = [
        i for i in linked_items()
        if i["item_id"] != item_id and i.get("account") != label
    ]
    items.append({
        "institution": institution,
        "account": account_label(institution),
        "access_token": access_token,
        "item_id": item_id,
        "cursor": None,
        "linked_at": datetime.now().isoformat(timespec="seconds"),
        "last_sync": None,
    })
    _write_items(items)


def _write_items(items: list):
    path = _tokens_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")


def account_label(institution: str) -> str:
    return _INSTITUTION_LABELS.get(
        str(institution).strip().lower(), str(institution).strip()
    )


# ----------------------------------------------------------------------
# Plaid REST
# ----------------------------------------------------------------------

def _post(endpoint: str, payload: dict) -> dict:
    """POST to Plaid; raises RuntimeError with Plaid's message on errors."""
    import requests

    host = _HOSTS.get(config.PLAID_ENV, _HOSTS["production"])
    body = {
        "client_id": config.PLAID_CLIENT_ID,
        "secret": config.PLAID_SECRET,
        **payload,
    }
    resp = requests.post(f"{host}{endpoint}", json=body, timeout=30)
    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        message = data.get("error_message") or data.get("error_code") or resp.text
        raise RuntimeError(message)
    return data


# ----------------------------------------------------------------------
# Normalization + sync
# ----------------------------------------------------------------------

def map_category(txn: dict) -> str:
    pfc = txn.get("personal_finance_category") or {}
    detailed = str(pfc.get("detailed") or "")
    primary = str(pfc.get("primary") or "")
    return (
        _PFC_DETAILED.get(detailed)
        or _PFC_PRIMARY.get(primary)
        or "Other"
    )


def normalize_added(added: list) -> pd.DataFrame:
    """Plaid transactions -> Scout rows.

    Pending transactions are skipped: Plaid replaces them with posted
    versions under a new id, which would double-count. Plaid's sign is
    positive = money out, so it flips to Scout's convention. The Plaid
    transaction_id becomes the dedupe hash, so re-syncs are always safe.
    """
    rows = []
    for txn in added:
        if txn.get("pending"):
            continue
        name = (txn.get("merchant_name") or txn.get("name") or "?").strip()
        rows.append({
            "date": str(txn.get("date")),
            "description": name,
            "amount": -float(txn.get("amount") or 0),
            "source_category": map_category(txn),
            "hash": f"plaid|{txn['transaction_id']}",
        })
    return pd.DataFrame(rows)


def sync_item(item: dict) -> dict:
    """Pull everything new for one linked bank. Returns a result dict;
    mutates item['cursor'] / item['last_sync'] on success."""
    added_total = skipped_total = 0
    cursor = item.get("cursor")
    while True:
        payload = {"access_token": item["access_token"], "count": 500}
        if cursor:
            payload["cursor"] = cursor
        data = _post("/transactions/sync", payload)
        frame = normalize_added(data.get("added", []))
        if not frame.empty:
            added, skipped = store.add_transactions(frame, item["account"])
            added_total += added
            skipped_total += skipped
        cursor = data.get("next_cursor") or cursor
        if not data.get("has_more"):
            break
    item["cursor"] = cursor
    item["last_sync"] = datetime.now().isoformat(timespec="seconds")
    return {"account": item["account"], "added": added_total,
            "skipped": skipped_total, "error": None}


def sync_all() -> list:
    """Sync every linked bank. Returns one result dict per item; an item
    that fails reports its error and doesn't stop the others."""
    items = linked_items()
    results = []
    for item in items:
        try:
            results.append(sync_item(item))
        except Exception as exc:
            results.append({"account": item.get("account", "?"),
                            "added": 0, "skipped": 0, "error": str(exc)})
    _write_items(items)  # persist advanced cursors / sync times
    return results
