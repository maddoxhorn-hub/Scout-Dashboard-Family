"""
Bank CSV parsers.

Each bank exports activity as CSV from its website; these parsers turn
any of them into one normalized frame:

    date (ISO str) | description | amount | source_category

with Scout's sign convention: negative = money out, positive = money in.
Cards report charges as positive numbers, so card profiles flip the sign;
checking accounts already report withdrawals as negative.
"""

import io

import pandas as pd

PROFILES = {
    "Discover": {
        "account": "Discover",
        "flip_sign": True,   # Discover: positive Amount = purchase
        "hint": "card.discover.com → Activity & Statements → Download (CSV)",
    },
    "Amex": {
        "account": "Amex",
        "flip_sign": True,   # Amex: positive Amount = charge
        "hint": "americanexpress.com → Statements & Activity → Download (CSV)",
    },
    "KeyBank": {
        "account": "KeyBank",
        "flip_sign": False,  # checking: negative already = money out
        "hint": "ibx.key.com → account → Download transactions (CSV)",
    },
    "Other (card-style: positive = charge)": {
        "account": None,
        "flip_sign": True,
        "hint": "Any card CSV with Date / Description / Amount columns",
    },
    "Other (bank-style: negative = money out)": {
        "account": None,
        "flip_sign": False,
        "hint": "Any bank CSV with Date / Description / Amount columns",
    },
}


def _norm(name: str) -> str:
    return str(name).lower().strip().replace(" ", "").replace(".", "").replace("_", "")


def _find(columns, *candidates):
    lookup = {_norm(c): c for c in columns}
    for cand in candidates:
        hit = lookup.get(_norm(cand))
        if hit is not None:
            return hit
    return None


def detect_profile(file_name: str, columns) -> str:
    """Best guess at the right profile for an uploaded CSV."""
    name = (file_name or "").lower()
    cols = {_norm(c) for c in columns}
    if "transdate" in cols and "category" in cols:
        return "Discover"
    if "discover" in name:
        return "Discover"
    if "cardmember" in cols or "amex" in name or "activity" in name and "category" not in cols:
        return "Amex"
    if "key" in name or ({"debit", "credit"} & cols):
        return "KeyBank"
    return "Other (bank-style: negative = money out)"


def parse_csv(data: bytes, profile_name: str) -> pd.DataFrame:
    """Normalize one uploaded CSV. Raises ValueError with a readable
    message when the file doesn't look like transaction data."""
    profile = PROFILES[profile_name]
    try:
        raw = pd.read_csv(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Couldn't read that file as CSV ({exc}).")

    if raw.empty:
        raise ValueError("That CSV has no rows.")

    date_col = _find(raw.columns, "Trans. Date", "Transaction Date", "Date", "Posted Date", "Post Date")
    desc_col = _find(raw.columns, "Description", "Memo", "Payee", "Merchant", "Details")
    amount_col = _find(raw.columns, "Amount", "Transaction Amount")
    debit_col = _find(raw.columns, "Debit", "Withdrawal", "Withdrawals")
    credit_col = _find(raw.columns, "Credit", "Deposit", "Deposits")
    cat_col = _find(raw.columns, "Category")

    if not date_col or not desc_col:
        raise ValueError(
            "Couldn't find Date and Description columns. Columns present: "
            + ", ".join(map(str, raw.columns))
        )

    df = pd.DataFrame()
    df["date"] = pd.to_datetime(raw[date_col], errors="coerce")
    df["description"] = raw[desc_col].astype(str).str.strip()

    def _num(series):
        return pd.to_numeric(
            series.astype(str).str.replace(r"[$,()]", "", regex=True),
            errors="coerce",
        )

    if amount_col:
        df["amount"] = _num(raw[amount_col])
    elif debit_col or credit_col:
        debit = _num(raw[debit_col]).fillna(0).abs() if debit_col else 0
        credit = _num(raw[credit_col]).fillna(0).abs() if credit_col else 0
        df["amount"] = credit - debit
    else:
        raise ValueError(
            "Couldn't find an Amount (or Debit/Credit) column. Columns "
            "present: " + ", ".join(map(str, raw.columns))
        )

    if profile["flip_sign"]:
        df["amount"] = -df["amount"]

    df["source_category"] = (
        raw[cat_col].astype(str).str.strip() if cat_col else None
    )

    bad = df["date"].isna() | df["amount"].isna()
    df = df[~bad].copy()
    if df.empty:
        raise ValueError("No rows with a valid date and amount were found.")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.attrs["dropped"] = int(bad.sum())
    return df.reset_index(drop=True)
