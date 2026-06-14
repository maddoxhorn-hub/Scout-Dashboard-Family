"""
Scout self-update.

Lets a family copy pull the latest *program* files from a public GitHub
repo with one press -- and NEVER touches anything personal.

Design rules (why this is safe):
  * Personal files are on a hard SKIP list: config.py (keys live here),
    config_local.py, the whole data/ folder (bank history, paper trades,
    tokens, the Trainer log), credentials, and any launcher. The updater
    refuses to overwrite them even if a release accidentally contained one.
  * The update is transactional. Each file we replace is backed up first;
    if anything goes wrong partway through, every change is rolled back and
    Scout is left exactly as it was. A half-applied update can't happen.
  * Pure standard library -- no extra packages -- so it runs the same on
    Windows and on a Mac.
  * Read-only with respect to the network: it only downloads a public zip.

Set UPDATE_REPO below to "<github-username>/<repo>" once the public repo
exists. Until then, checks report "update channel not set up yet" instead
of erroring.
"""

from __future__ import annotations

import io
import os
import shutil
import ssl
import tempfile
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Where updates come from. PUBLIC repo, sanitized code only -- never secrets.
# Format: "username/reponame".  Branch is usually "main".
# An env var can override it (handy for testing) without editing code.
# ---------------------------------------------------------------------------
UPDATE_REPO = os.environ.get("SCOUT_UPDATE_REPO", "maddoxhorn-hub/Scout-Dashboard-Family")
UPDATE_BRANCH = os.environ.get("SCOUT_UPDATE_BRANCH", "main")

APP_DIR = Path(__file__).resolve().parent
VERSION_FILE = APP_DIR / "VERSION"
CHANGELOG_FILE = APP_DIR / "CHANGELOG.md"

_TIMEOUT = 20  # seconds for any single network call

# --- Things the updater must NEVER create, overwrite, or delete ------------
# Matched against each file's path RELATIVE to the app folder, using forward
# slashes. A path is skipped if its first segment is a skip-dir, its name is
# a skip-file, or its suffix is a skip-suffix.
_SKIP_DIRS = {
    "data", ".venv", "venv", ".git", "__pycache__", ".claude",
    "tools", ".scout_backup", ".scout_download",
}
_SKIP_FILES = {
    "config.py", "config_local.py",
    "credentials.json", "schwab_token.json", "token.json",
    "alpaca_options.json", "plaid_keys.json", "plaid_tokens.json",
    "webull_openapi.json",
}
_SKIP_SUFFIXES = {".pyc", ".command", ".bat", ".zip", ".log"}


def _is_personal(rel_posix: str) -> bool:
    """True if a relative path must be left untouched by updates."""
    parts = rel_posix.split("/")
    if parts[0] in _SKIP_DIRS:
        return True
    name = parts[-1]
    if name in _SKIP_FILES:
        return True
    suffix = ("." + name.rsplit(".", 1)[1]) if "." in name else ""
    return suffix in _SKIP_SUFFIXES


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------
def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _as_tuple(v: str) -> tuple:
    out = []
    for part in v.strip().split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return _as_tuple(remote) > _as_tuple(local)


def is_configured() -> bool:
    return "__SET_THIS__" not in UPDATE_REPO and "/" in UPDATE_REPO


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def _ctx() -> ssl.SSLContext:
    # Default verification; Macs sometimes need certifi but the system store
    # works for github.com on a normal install.
    return ssl.create_default_context()


def _get(url: str, timeout: int = _TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Scout-Updater"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
        return resp.read()


def _raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}/{path}"


def _zip_url() -> str:
    return f"https://codeload.github.com/{UPDATE_REPO}/zip/refs/heads/{UPDATE_BRANCH}"


def check(timeout: int = _TIMEOUT) -> dict:
    """Look up the latest published version.

    Returns a dict: {ok, configured, available, current, latest, notes, error}.
    Never raises -- the UI shows .error if something went wrong.
    """
    result = {
        "ok": False, "configured": is_configured(), "available": False,
        "current": current_version(), "latest": None, "notes": "", "error": None,
    }
    if not result["configured"]:
        result["error"] = "Update channel isn't set up yet."
        return result
    try:
        latest = _get(_raw_url("VERSION"), timeout=timeout).decode("utf-8").strip()
        result["latest"] = latest
        try:
            result["notes"] = _get(_raw_url("CHANGELOG.md"), timeout=timeout).decode("utf-8")
        except urllib.error.URLError:
            result["notes"] = ""
        result["available"] = is_newer(latest, result["current"])
        result["ok"] = True
    except urllib.error.HTTPError as exc:
        result["error"] = (
            "Couldn't find the update (is the repo public?). "
            f"[{exc.code}]"
        )
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
        result["error"] = f"No internet, or GitHub unreachable ({exc})."
    except Exception as exc:  # never let the UI crash on a check
        result["error"] = f"Update check failed ({exc})."
    return result


# ---------------------------------------------------------------------------
# Apply -- transactional, with rollback
# ---------------------------------------------------------------------------
def _download_zip() -> zipfile.ZipFile:
    data = _get(_zip_url())
    return zipfile.ZipFile(io.BytesIO(data))


def apply_update() -> dict:
    """Download the latest release and replace program files only.

    Returns {ok, from_version, to_version, changed, error}. On any failure
    every change is rolled back, so Scout is never left half-updated.
    """
    out = {"ok": False, "from_version": current_version(),
           "to_version": None, "changed": 0, "error": None}
    if not is_configured():
        out["error"] = "Update channel isn't set up yet."
        return out

    backup_dir = Path(tempfile.mkdtemp(prefix="scout_backup_"))
    applied: list[tuple[Path, Path | None]] = []  # (target, backup or None=new)
    try:
        zf = _download_zip()
        names = zf.namelist()
        if not names:
            raise RuntimeError("downloaded update was empty")
        # GitHub zips nest everything under "<repo>-<branch>/".
        root = names[0].split("/", 1)[0] + "/"

        # Build the list of (relative_path, member) to apply.
        members = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if not name.startswith(root):
                continue
            rel = name[len(root):]
            if not rel or _is_personal(rel):
                continue
            members.append((rel, info))

        if not members:
            raise RuntimeError("update contained no program files")

        for rel, info in members:
            target = APP_DIR / rel
            if target.exists():
                bkp = backup_dir / rel
                bkp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, bkp)
                applied.append((target, bkp))
            else:
                applied.append((target, None))
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

        out["to_version"] = current_version()  # VERSION was just overwritten
        out["changed"] = len(members)
        out["ok"] = True
        return out

    except Exception as exc:
        # Roll everything back, newest change first.
        for target, bkp in reversed(applied):
            try:
                if bkp is not None:
                    shutil.copy2(bkp, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                pass
        out["error"] = f"Update failed and was rolled back ({exc})."
        return out
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


if __name__ == "__main__":
    import json
    print(json.dumps(check(), indent=2))
