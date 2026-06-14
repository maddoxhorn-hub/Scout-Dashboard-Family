"""
KeyBank statement PDF -> transactions.

KeyBank's online banking hands out monthly statements as PDFs
(Statement_MMYYYY_xxxx.pdf). Each one lists Deposits and Withdrawals
sections plus beginning/ending balances. The balances make the parse
self-verifying: if the transactions found don't reconcile to the penny
with the statement's own arithmetic, the import is refused outright --
a partial import would be worse than none.
"""

import io
import re
from datetime import datetime

import pandas as pd

# Section headings -> the sign of every transaction inside them.
_SECTION_SIGNS = {
    "Deposits": +1,
    "Additions": +1,
    "Withdrawals": -1,
    "Subtractions": -1,
    "Checks": -1,
    "Fees and charges": -1,
    "Fees and Charges": -1,
}

_TXN = re.compile(r"^(\d{2})/(\d{2})\s+(.+?)\s+(-?)\$([\d,]+\.\d{2})$")
_PERIOD = re.compile(
    r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+to\s+([A-Z][a-z]+ \d{1,2}, \d{4})"
)
_BEGIN = re.compile(r"Beginning Balance.*?(-?)\$([\d,]+\.\d{2})")
_END = re.compile(r"Ending Balance.*?(-?)\$([\d,]+\.\d{2})")


def _money(sign: str, digits: str) -> float:
    value = float(digits.replace(",", ""))
    return -value if sign == "-" else value


def looks_like_keybank(data: bytes, file_name: str = "") -> bool:
    """Cheap check: KeyBank statement filename and/or branding text."""
    if re.match(r"(?i)^statement_\d{6}_\d{4}\.pdf$", file_name or ""):
        return True
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            first = pdf.pages[0].extract_text() or ""
        return "KeyBank" in first
    except Exception:
        return False


def parse_statement(data: bytes) -> pd.DataFrame:
    """Return the normalized frame (date, description, amount,
    source_category). Raises ValueError with a readable message when the
    statement can't be parsed *and verified*."""
    import pdfplumber

    lines = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())

    text = "\n".join(lines)
    if "KeyBank" not in text:
        raise ValueError("That PDF doesn't look like a KeyBank statement.")

    period = _PERIOD.search(text)
    begin = _BEGIN.search(text)
    end = _END.search(text)
    if not (period and begin and end):
        raise ValueError(
            "Couldn't find the statement period and balances in that PDF — "
            "the layout may have changed."
        )
    start = datetime.strptime(period.group(1), "%B %d, %Y")
    finish = datetime.strptime(period.group(2), "%B %d, %Y")
    begin_balance = _money(begin.group(1), begin.group(2))
    end_balance = _money(end.group(1), end.group(2))

    rows = []
    sign = None
    for raw in lines:
        line = raw.strip()
        if line in _SECTION_SIGNS:
            sign = _SECTION_SIGNS[line]
            continue
        if line.startswith("Total ") or line.startswith("Account Updates"):
            sign = None
            continue
        if sign is None:
            continue
        match = _TXN.match(line)
        if not match:
            continue
        month, day = int(match.group(1)), int(match.group(2))
        # statements can span a year boundary (Dec -> Jan)
        year = start.year if month == start.month else finish.year
        amount = sign * _money(match.group(4), match.group(5))
        rows.append({
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "description": match.group(3).strip(),
            "amount": amount,
            "source_category": None,
        })

    if not rows:
        raise ValueError("No transactions found in that statement.")

    # The statement's own arithmetic must agree with what was parsed.
    delta = round(sum(r["amount"] for r in rows), 2)
    expected = round(end_balance - begin_balance, 2)
    if abs(delta - expected) > 0.01:
        raise ValueError(
            f"Parsed {len(rows)} transactions but they don't reconcile with "
            "the statement's beginning/ending balances — refusing to import "
            "a partial statement. (The PDF may contain a section Scout "
            "doesn't know yet.)"
        )

    return pd.DataFrame(rows)
