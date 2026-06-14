"""
Local transaction store -- a single SQLite file, nothing leaves the machine.

Sign convention everywhere in Scout: amount < 0 is money out (spending),
amount > 0 is money in (income, refunds). Importers normalize each bank's
format to this before anything lands here.
"""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import config

# Categories that exist even before any rule matches them. "Transfers &
# Payments" is excluded from spending math: a card payment is not spending
# (the purchases on the card already were).
CATEGORIES = [
    "Groceries", "Dining", "Gas & Auto", "Shopping", "Subscriptions",
    "Utilities", "Housing", "Health", "Travel", "Entertainment",
    "Insurance", "Fees", "Income", "Transfers & Payments", "Other",
]

NON_SPENDING = {"Transfers & Payments", "Income"}

_DEFAULT_RULES = [
    # keyword (case-insensitive substring of description) -> category
    ("KROGER", "Groceries"), ("ALDI", "Groceries"), ("WALMART", "Groceries"),
    ("COSTCO", "Groceries"), ("TRADER JOE", "Groceries"), ("WHOLEFDS", "Groceries"),
    ("MEIJER", "Groceries"), ("GIANT EAGLE", "Groceries"),
    ("MCDONALD", "Dining"), ("CHIPOTLE", "Dining"), ("STARBUCKS", "Dining"),
    ("DOORDASH", "Dining"), ("UBER EATS", "Dining"), ("GRUBHUB", "Dining"),
    ("CHICK-FIL-A", "Dining"), ("TACO BELL", "Dining"), ("WENDY", "Dining"),
    ("DUNKIN", "Dining"), ("PIZZA", "Dining"),
    ("SHELL", "Gas & Auto"), ("BP#", "Gas & Auto"), ("EXXON", "Gas & Auto"),
    ("SPEEDWAY", "Gas & Auto"), ("MARATHON", "Gas & Auto"), ("CIRCLE K", "Gas & Auto"),
    ("AUTOZONE", "Gas & Auto"), ("VALVOLINE", "Gas & Auto"),
    ("AMAZON", "Shopping"), ("AMZN", "Shopping"), ("TARGET", "Shopping"),
    ("BEST BUY", "Shopping"), ("EBAY", "Shopping"), ("ETSY", "Shopping"),
    ("NETFLIX", "Subscriptions"), ("SPOTIFY", "Subscriptions"), ("HULU", "Subscriptions"),
    ("DISNEY", "Subscriptions"), ("YOUTUBE", "Subscriptions"), ("APPLE.COM/BILL", "Subscriptions"),
    ("PRIME VIDEO", "Subscriptions"), ("MAX.COM", "Subscriptions"), ("OPENAI", "Subscriptions"),
    ("ANTHROPIC", "Subscriptions"),
    ("DUKE ENERGY", "Utilities"), ("ELECTRIC", "Utilities"), ("WATER", "Utilities"),
    ("SPECTRUM", "Utilities"), ("XFINITY", "Utilities"), ("AT&T", "Utilities"),
    ("VERIZON", "Utilities"), ("T-MOBILE", "Utilities"),
    ("RENT", "Housing"), ("MORTGAGE", "Housing"),
    ("CVS", "Health"), ("WALGREENS", "Health"), ("PHARMACY", "Health"),
    ("DELTA AIR", "Travel"), ("UNITED", "Travel"), ("SOUTHWES", "Travel"),
    ("AIRBNB", "Travel"), ("MARRIOTT", "Travel"), ("UBER", "Travel"), ("LYFT", "Travel"),
    ("AMC", "Entertainment"), ("TICKETMASTER", "Entertainment"), ("STEAM", "Entertainment"),
    ("GEICO", "Insurance"), ("PROGRESSIVE", "Insurance"), ("STATE FARM", "Insurance"),
    ("ALLSTATE", "Insurance"),
    ("INTEREST CHARGE", "Fees"), ("LATE FEE", "Fees"), ("ANNUAL FEE", "Fees"),
    ("OVERDRAFT", "Fees"),
    ("PAYROLL", "Income"), ("DIRECT DEP", "Income"), ("DEPOSIT", "Income"),
    ("INTEREST PAYMENT", "Income"), ("CASHBACK BONUS", "Income"), ("REWARD", "Income"),
    ("PAYMENT THANK YOU", "Transfers & Payments"), ("AUTOPAY", "Transfers & Payments"),
    ("INTERNET TRF", "Transfers & Payments"), ("AMEX EPAYMENT", "Transfers & Payments"),
    ("ONLINE PAYMENT", "Transfers & Payments"), ("MOBILE PAYMENT", "Transfers & Payments"),
    ("TRANSFER", "Transfers & Payments"), ("ZELLE", "Transfers & Payments"),
    ("VENMO", "Transfers & Payments"), ("ACH PMT", "Transfers & Payments"),
    ("CARDMEMBER SERV", "Transfers & Payments"), ("DISCOVER E-PAYMENT", "Transfers & Payments"),
]


def _connect(db_path=None):
    path = Path(db_path or config.BUDGET_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            hash TEXT UNIQUE NOT NULL,
            account TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            source_category TEXT,
            imported_at TEXT NOT NULL
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY,
            keyword TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL
        )"""
    )
    if con.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0:
        con.executemany(
            "INSERT OR IGNORE INTO rules (keyword, category) VALUES (?, ?)",
            _DEFAULT_RULES,
        )
        con.commit()
    return con


# ----------------------------------------------------------------------
# Categorization
# ----------------------------------------------------------------------

def get_rules(db_path=None) -> pd.DataFrame:
    with _connect(db_path) as con:
        return pd.read_sql_query(
            "SELECT keyword, category FROM rules ORDER BY keyword", con
        )


def save_rules(rules: pd.DataFrame, db_path=None):
    """Replace the rule set with the given (keyword, category) frame."""
    with _connect(db_path) as con:
        con.execute("DELETE FROM rules")
        rows = [
            (str(k).strip().upper(), str(c).strip())
            for k, c in zip(rules["keyword"], rules["category"])
            if str(k).strip() and str(c).strip()
        ]
        con.executemany(
            "INSERT OR IGNORE INTO rules (keyword, category) VALUES (?, ?)", rows
        )
        con.commit()


def categorize(description: str, source_category: str, rules: pd.DataFrame) -> str:
    """Source category from the bank wins if it maps cleanly; else rules."""
    desc = str(description).upper()
    # Longest keyword first, so "UBER EATS" (Dining) beats "UBER" (Travel).
    ordered = sorted(
        zip(rules["keyword"], rules["category"]),
        key=lambda kc: len(str(kc[0])),
        reverse=True,
    )
    for keyword, category in ordered:
        if keyword and keyword in desc:
            return category
    src = str(source_category or "").strip()
    if src:
        mapped = _map_source_category(src)
        if mapped:
            return mapped
    return "Other"


def _map_source_category(src: str):
    """Best-effort mapping of bank-provided categories onto Scout's."""
    if src in CATEGORIES:  # already one of ours (e.g. mapped from Plaid)
        return src
    s = src.lower()
    table = {
        "supermarkets": "Groceries", "grocer": "Groceries",
        "restaurant": "Dining", "dining": "Dining", "fast food": "Dining",
        "gasoline": "Gas & Auto", "gas": "Gas & Auto", "automotive": "Gas & Auto",
        "merchandise": "Shopping", "department": "Shopping", "online shopping": "Shopping",
        "services": "Subscriptions", "internet": "Subscriptions",
        "utilities": "Utilities", "phone": "Utilities", "cable": "Utilities",
        "medical": "Health", "health": "Health", "drug": "Health",
        "travel": "Travel", "airline": "Travel", "lodging": "Travel",
        "entertainment": "Entertainment",
        "insurance": "Insurance",
        "fee": "Fees", "interest": "Fees",
        "payments and credits": "Transfers & Payments", "payment": "Transfers & Payments",
        "awards and rebate": "Income", "cashback": "Income",
    }
    for fragment, category in table.items():
        if fragment in s:
            return category
    return None


def recategorize_all(db_path=None) -> int:
    """Re-run the rules over every stored transaction. Returns rows changed."""
    rules = get_rules(db_path)
    with _connect(db_path) as con:
        df = pd.read_sql_query(
            "SELECT id, description, source_category, category FROM transactions", con
        )
        changed = 0
        for _, row in df.iterrows():
            new_cat = categorize(row["description"], row["source_category"], rules)
            if new_cat != row["category"]:
                con.execute(
                    "UPDATE transactions SET category=? WHERE id=?",
                    (new_cat, row["id"]),
                )
                changed += 1
        con.commit()
    return changed


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------

def _row_hash(account, date, description, amount, occurrence) -> str:
    key = f"{account}|{date}|{str(description).strip().upper()}|{amount:.2f}|{occurrence}"
    return hashlib.sha1(key.encode()).hexdigest()


def add_transactions(df: pd.DataFrame, account: str, db_path=None):
    """Insert normalized rows (date, description, amount, source_category).

    Re-importing an overlapping CSV is safe: rows hash identically and are
    skipped. Genuine same-day duplicates survive because the hash includes
    an occurrence counter within the import. Rows that arrive with their
    own stable id (a "hash" column -- e.g. Plaid transaction ids) use that
    instead.
    Returns (added, skipped).
    """
    if df.empty:
        return 0, 0

    rules = get_rules(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    df = df.copy()
    df["occurrence"] = df.groupby(
        ["date", "description", "amount"]
    ).cumcount()

    added = skipped = 0
    with _connect(db_path) as con:
        for _, row in df.iterrows():
            h = row["hash"] if "hash" in df.columns else _row_hash(
                account, row["date"], row["description"],
                row["amount"], row["occurrence"],
            )
            category = categorize(
                row["description"], row.get("source_category"), rules
            )
            try:
                con.execute(
                    """INSERT INTO transactions
                       (hash, account, date, description, amount, category,
                        source_category, imported_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        h, account, row["date"], str(row["description"]).strip(),
                        float(row["amount"]), category,
                        row.get("source_category"), now,
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        con.commit()
    return added, skipped


def set_category(txn_id: int, category: str, db_path=None):
    with _connect(db_path) as con:
        con.execute(
            "UPDATE transactions SET category=? WHERE id=?", (category, txn_id)
        )
        con.commit()


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------

def transactions(db_path=None) -> pd.DataFrame:
    with _connect(db_path) as con:
        df = pd.read_sql_query(
            "SELECT id, account, date, description, amount, category "
            "FROM transactions ORDER BY date DESC, id DESC",
            con,
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def accounts_summary(db_path=None) -> pd.DataFrame:
    with _connect(db_path) as con:
        return pd.read_sql_query(
            "SELECT account, COUNT(*) AS transactions, MIN(date) AS first, "
            "MAX(date) AS last FROM transactions GROUP BY account",
            con,
        )


def change_signal(db_path=None) -> tuple:
    """Cheap (row_count, latest_import) pair -- changes whenever new data
    lands. The app polls this to refresh itself when the watcher imports."""
    with _connect(db_path) as con:
        return con.execute(
            "SELECT COUNT(*), MAX(imported_at) FROM transactions"
        ).fetchone()


@st.cache_data(ttl=120, show_spinner=False)
def _txns_cached(_signal):
    return transactions()


def transactions_cached() -> pd.DataFrame:
    """View-facing cached read of the whole table. Keyed on change_signal, so
    it refreshes the moment new data lands but is free on every other rerun
    (the 10s pulse, widget clicks). Refresh's st.cache_data.clear() busts it."""
    return _txns_cached(change_signal())


def last_imports(db_path=None) -> dict:
    """{account: most recent imported_at iso string} -- when each bank's
    data last actually arrived (any source: watcher, manual CSV, Plaid)."""
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT account, MAX(imported_at) FROM transactions GROUP BY account"
        ).fetchall()
    return {account: ts for account, ts in rows}
