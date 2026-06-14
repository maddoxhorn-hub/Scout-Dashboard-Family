"""
The bank-file pickup pipeline.

How a refresh works, end to end:
  1. On launch (or the "Get bank files" button), open_bank_pages() opens
     the stale banks' download pages in their own browser window and
     notes the session in data/bank_session.json.
  2. The user clicks Download at each bank -- the only step that can't
     be automated without storing bank logins, which Scout refuses to do.
  3. A background thread in the app (watch_forever) sees each CSV land in
     the Downloads folder, imports it through the same dedupe/categorize
     path as manual imports, and DELETES the file the moment its rows are
     safely in the database -- no plaintext bank history lingers on disk.
     The database (data/budget.db) is the only place the data persists,
     and it's what every chart and table reads from.
  4. When every bank in the session has delivered, the pickup window is
     closed automatically.

Only files that confidently look like Discover / Amex / KeyBank exports
are touched; everything else in Downloads is ignored.
"""

import ctypes
import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from budget import importers, store

SESSION_PATH = Path("data/bank_session.json")
STATE_PATH = Path("data/watch_state.json")
AUTO_COOLDOWN_HOURS = 6      # don't reopen the bank window more often than this
SESSION_MAX_MINUTES = 45     # stop trying to auto-close after this long


# ----------------------------------------------------------------------
# Where is the real Downloads folder? (OneDrive may have moved it)
# ----------------------------------------------------------------------

def downloads_path() -> Path:
    try:
        from ctypes import windll, wintypes  # noqa: F401

        FOLDERID_Downloads = ctypes.c_char_p(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        guid = GUID(
            0x374DE290, 0x123F, 0x4565,
            (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
        )
        path_ptr = ctypes.c_wchar_p()
        if windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        ) == 0:
            result = Path(path_ptr.value)
            windll.ole32.CoTaskMemFree(path_ptr)
            return result
    except Exception:
        pass
    return Path.home() / "Downloads"


# ----------------------------------------------------------------------
# Strict detection -- which bank does this Downloads CSV belong to?
# ----------------------------------------------------------------------

def detect_bank(file_path: Path) -> str:
    """Return 'Discover' | 'Amex' | 'KeyBank' | 'KeyBank PDF' | None.

    Deliberately stricter than the manual importer's guesser: a random
    file in Downloads must never be swallowed by mistake.
    """
    name = file_path.name.lower()

    if file_path.suffix.lower() == ".pdf":
        from budget import keybank_pdf

        # KeyBank hands out statements as Statement_MMYYYY_xxxx.pdf
        if re.match(r"^statement_\d{6}_\d{4}\.pdf$", name):
            return "KeyBank PDF"
        if keybank_pdf.looks_like_keybank(file_path.read_bytes()):
            return "KeyBank PDF"
        return None
    try:
        cols = {
            importers._norm(c)
            for c in pd.read_csv(file_path, nrows=0).columns
        }
    except Exception:
        return None

    has_core = bool(
        {"date", "transdate", "transactiondate", "posteddate", "postdate"} & cols
    ) and bool({"description", "memo", "payee", "details"} & cols)

    if "transdate" in cols and "category" in cols:
        return "Discover"
    if "discover" in name and has_core:
        return "Discover"
    if "cardmember" in cols and has_core:
        return "Amex"
    if re.search(r"amex|american[\s_-]?express", name) and has_core:
        return "Amex"
    if name.startswith("activity") and has_core and "category" not in cols:
        return "Amex"  # Amex's default export is "activity.csv"
    if re.search(r"key[\s_-]?bank|(?<![a-z])key(?![a-z])", name) and has_core:
        return "KeyBank"
    if {"debit", "credit"} & cols and has_core:
        return "KeyBank"
    return None


# ----------------------------------------------------------------------
# One scan pass over Downloads
# ----------------------------------------------------------------------

def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}"


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"processed": {}}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # keep the ledger from growing forever
    processed = state.get("processed", {})
    if len(processed) > 400:
        keep = sorted(processed.items(), key=lambda kv: kv[1])[-300:]
        state["processed"] = dict(keep)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def scan_once(folder: Path = None) -> list:
    """Import any new bank CSVs sitting in Downloads.

    Returns a list of result dicts. Each file is deleted only AFTER its
    rows are committed to the database; if the delete itself fails (e.g.
    antivirus briefly holds the file), the next scan retries and the
    dedupe makes the re-import a no-op. Unrecognized files are never
    touched.
    """
    folder = folder or downloads_path()
    if not folder.exists():
        return []

    state = _load_state()
    processed = state.setdefault("processed", {})
    results = []

    candidates = sorted(folder.glob("*.csv")) + sorted(folder.glob("*.pdf"))
    for path in candidates:
        try:
            # skip files still being written (downloaded moments ago)
            if time.time() - path.stat().st_mtime < 2:
                continue
            fp = _fingerprint(path)
            if fp in processed:
                continue
            bank = detect_bank(path)
            if bank is None:
                processed[fp] = datetime.now().isoformat(timespec="seconds")
                continue
            if bank == "KeyBank PDF":
                from budget import keybank_pdf

                frame = keybank_pdf.parse_statement(path.read_bytes())
                bank = "KeyBank"
            else:
                frame = importers.parse_csv(path.read_bytes(), bank)
            added, skipped = store.add_transactions(frame, bank)
            path.unlink()  # rows are committed -- the file is now redundant
            processed[fp] = datetime.now().isoformat(timespec="seconds")
            _mark_session_delivery(bank)
            results.append(
                {"file": path.name, "bank": bank,
                 "added": added, "skipped": skipped}
            )
        except Exception as exc:
            # leave the file alone; surface the problem in the results
            results.append({"file": path.name, "bank": None, "error": str(exc)})

    _save_state(state)
    return results


# ----------------------------------------------------------------------
# Staleness -- which banks need fresh files?
# ----------------------------------------------------------------------

def stale_banks() -> list:
    """Banks whose data is older than BANK_REFRESH_DAYS (or missing)."""
    last = store.last_imports()
    cutoff = datetime.now() - timedelta(days=config.BANK_REFRESH_DAYS)
    stale = []
    for bank in config.BANK_ACCOUNTS:
        ts = last.get(bank)
        if ts is None or datetime.fromisoformat(ts) < cutoff:
            stale.append(bank)
    return stale


# ----------------------------------------------------------------------
# The pickup window
# ----------------------------------------------------------------------

def _browser_path():
    """Chrome first, on purpose: the user's bank logins and saved
    passwords live in their Google profile, so anything Scout opens must
    land where those autofill. Edge is only a fallback. Includes the
    macOS Chrome path so this module ports cleanly."""
    import os

    for candidate in (
        rf"{os.environ.get('ProgramFiles', '')}\Google\Chrome\Application\chrome.exe",
        rf"{os.environ.get('ProgramFiles(x86)', '')}\Google\Chrome\Application\chrome.exe",
        rf"{os.environ.get('LOCALAPPDATA', '')}\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        rf"{os.environ.get('ProgramFiles', '')}\Microsoft\Edge\Application\msedge.exe",
        rf"{os.environ.get('ProgramFiles(x86)', '')}\Microsoft\Edge\Application\msedge.exe",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def open_url(url: str):
    """Open a URL in Chrome (saved logins live there); default browser
    as a last resort."""
    browser = _browser_path()
    if browser:
        subprocess.Popen([browser, url], creationflags=_no_window_flag())
    else:
        import webbrowser

        webbrowser.open_new_tab(url)


def _no_window_flag() -> int:
    import sys

    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def open_bank_pages(banks=None, force=False) -> dict:
    """Open the stale banks' download pages in their own browser window.

    Returns {"opened": [...]} or {"opened": [], "reason": "..."}.
    With force=True all banks open regardless of staleness/cooldown.
    """
    session = _load_session()
    if not force and session.get("opened_at"):
        opened = datetime.fromisoformat(session["opened_at"])
        if datetime.now() - opened < timedelta(hours=AUTO_COOLDOWN_HOURS):
            return {"opened": [], "reason": "cooldown"}

    banks = banks or (list(config.BANK_ACCOUNTS) if force else stale_banks())
    banks = [b for b in banks if b in config.BANK_DOWNLOAD_PAGES]
    if not banks:
        return {"opened": [], "reason": "fresh"}

    urls = [config.BANK_DOWNLOAD_PAGES[b] for b in banks]
    browser = _browser_path()
    if browser:
        subprocess.Popen(
            [browser, "--new-window", *urls],
            creationflags=_no_window_flag(),
        )
    else:
        import webbrowser

        for url in urls:
            webbrowser.open_new_tab(url)

    _save_session({
        "opened_at": datetime.now().isoformat(timespec="seconds"),
        "banks": banks,
        "delivered": [],
        "closed": False,
    })
    return {"opened": banks}


def _load_session() -> dict:
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_session(session: dict):
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(session, indent=2), encoding="utf-8")


def _mark_session_delivery(bank: str):
    session = _load_session()
    if not session.get("opened_at") or session.get("closed"):
        return
    if bank not in session.setdefault("delivered", []):
        session["delivered"].append(bank)
        _save_session(session)


_BANK_TITLE = re.compile(
    r"discover|american express|amex|keybank|key bank", re.IGNORECASE
)


def _bank_window_handles() -> list:
    """Top-level window handles whose title looks like a bank page.

    Window-level (not process-level): one browser process hosts many
    windows, and Scout's own app window must never be touched.
    Windows-only; elsewhere the pickup window simply stays open.
    """
    import sys

    if sys.platform != "win32":
        return []

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND, wintypes.LPWSTR, ctypes.c_int,
    ]
    handles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value
                if _BANK_TITLE.search(title) and "Scout" not in title:
                    handles.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return handles


def close_bank_windows() -> int:
    """Gracefully close (WM_CLOSE) every bank-titled browser window."""
    import sys

    if sys.platform != "win32":
        return 0

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [
        wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
    ]
    WM_CLOSE = 0x0010
    handles = _bank_window_handles()
    for hwnd in handles:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return len(handles)


def maybe_close_pickup_window():
    """Close the pickup window once every bank it opened has delivered.

    Window-titles are matched, never processes, so only windows actually
    showing a bank page can be affected. If nothing matches, the window
    simply stays open -- the harmless failure mode.
    """
    session = _load_session()
    if not session.get("opened_at") or session.get("closed"):
        return
    opened_at = datetime.fromisoformat(session["opened_at"])
    expired = datetime.now() - opened_at > timedelta(minutes=SESSION_MAX_MINUTES)
    done = set(session.get("banks", [])) <= set(session.get("delivered", []))
    if not done and not expired:
        return

    session["closed"] = True
    _save_session(session)
    if done:  # timed out instead -- user probably closed it themselves
        try:
            close_bank_windows()
        except Exception:
            pass


# ----------------------------------------------------------------------
# The background watcher (runs inside the app server)
# ----------------------------------------------------------------------

def watch_forever(interval=4):
    while True:
        try:
            scan_once()
            maybe_close_pickup_window()
        except Exception:
            pass
        time.sleep(interval)
