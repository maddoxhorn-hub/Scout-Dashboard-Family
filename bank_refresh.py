"""
Open the banks' download pages so fresh CSVs can be grabbed.

Run automatically by the desktop launcher on every start:
    pythonw.exe bank_refresh.py --auto
        Opens only banks whose data is older than BANK_REFRESH_DAYS,
        and never more than once per cooldown window.

Or by hand / from the Budget page:
    python.exe bank_refresh.py --force
        Opens all banks now.

Scout's background watcher does the rest: it imports each CSV the moment
it lands in Downloads and closes the pickup window when all are in.
"""

import os
import sys
from pathlib import Path

os.chdir(Path(__file__).parent)

from budget import downloads


def main():
    force = "--force" in sys.argv
    dry = "--dry-run" in sys.argv
    if dry:
        stale = downloads.stale_banks()
        print(f"stale banks: {stale or 'none'}")
        print(f"would open: {list(downloads.stale_banks()) if not force else 'all banks'}")
        return
    result = downloads.open_bank_pages(force=force)
    if result["opened"]:
        print(f"Opened download pages for: {', '.join(result['opened'])}")
    else:
        print(f"Nothing opened ({result.get('reason', 'no banks configured')}).")


if __name__ == "__main__":
    main()
