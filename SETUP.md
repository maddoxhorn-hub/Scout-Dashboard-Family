# Scout

Your personal command center: bot performance, Schwab balances, spending
across your bank accounts, and every trading link you use — one window,
on your machine, read-only by design. Nothing in Scout can place an
order or move a dollar.

> **Status on this machine (June 12, 2026):** Everything below is done
> except the Schwab keys (waiting on their approval) and your first bank
> CSV import. **Double-click "Scout Dashboard" on the desktop** and
> you're in.

---

## Opening Scout

- **Desktop icon** — "Scout Dashboard" starts the local server if it
  isn't running and opens Scout in its own window. First open takes a
  few seconds; after that it's instant.
- Or from a terminal in this folder: `.venv\Scripts\python.exe -m
  streamlit run app.py`, then visit http://localhost:8501.
- Deep links work: `http://localhost:8501/?page=Budget` opens a specific
  page (Overview, Trading, Schwab, Budget, Links).

The server keeps running quietly in the background after you close the
window — that's what makes reopening instant. It only ever listens on
this machine.

## The pages

- **Overview** — every balance on one screen, this month's spending and
  cash flow, and the status of each connection.
- **Trading** — the bots' realized P&L, equity curve with drawdown, and
  the Backtest-vs-live yardstick in R. The 1R control sits next to that
  section (defaults to `R_DOLLARS` in config.py).
- **Schwab** — live balances and positions once connected; until then, a
  checklist of exactly where you are in their approval process.
- **Budget** — spending across Discover, Amex, and KeyBank: monthly
  category breakdown, 12-month trend, top merchants, and a transaction
  browser where fixing a category is one click.
- **Links** — every site and local file you use for trading and
  investing. Edit `QUICK_LINKS` and `LOCAL_SHORTCUTS` in config.py to
  make it yours.

---

## Part 1 — The trade log (done)

`credentials.json` (copied from the bot folder) gives Scout *view-only*
access to the bots' Google Sheet. Scout opens the sheet by ID — the same
`SHEET_ID` as the bot's config — and finds the trade-log tab by its
name (`Sheet1`), so renaming or reordering tabs can't break it.

## Part 2 — Schwab (waiting on approval)

The one-time dance, continued from where you are:

1. ~~Create a developer account at developer.schwab.com~~ ✓
2. ~~Create an app with callback `https://127.0.0.1:8182`~~ ✓
3. **Wait for "Ready For Use."** "Approved – Pending" still means *not
   approved*. Check back over the next few days.
4. Copy the **App Key** and **Secret** into `config.py`.
5. In this folder run: `.venv\Scripts\python.exe schwab_login.py` — log
   in with your regular brokerage credentials. Two normal-but-alarming
   moments: the browser may warn about `127.0.0.1` not being private
   (click Advanced → Proceed — that's the script's own page), and
   `schwab_token.json` appears in this folder (that file *is* your
   login; treat it like a password).
6. Refresh Scout. Done.

**The weekly ritual:** Schwab expires these logins about every 7 days.
When the Schwab page starts erroring, run `schwab_login.py` again —
thirty seconds.

## Part 3 — Bank accounts (Discover · Amex · KeyBank)

Scout's main path is the **bank-file pickup**: free, automatic, and as
separated from the banks as possible — Scout never sees a bank login.

### How a refresh works

1. **When you launch Scout**, any bank whose data is older than
   `BANK_REFRESH_DAYS` (default 7) gets its download page opened in a
   **separate browser window** — your other windows are untouched. The
   Budget page's **Get bank files** button does the same on demand.
2. **You click Download at each bank** (your browser already remembers
   the logins). That click is the one thing Scout won't automate — doing
   so would mean storing your bank credentials, which defeats the point.
3. **Scout watches the Downloads folder.** The moment each CSV lands it
   is imported, deduplicated, categorized — and then **deleted**, the
   instant its rows are safely in Scout's local database. No plaintext
   bank file lingers in Downloads or anywhere else; the database
   (`data/budget.db`) is the single place the data lives, and it's what
   every chart reads from. Need history again? Re-download from the
   bank — duplicates are always skipped.
4. When every bank has delivered, **the pickup window closes itself.**

Tuning: `BANK_REFRESH_DAYS` in config.py (0 = open the banks on every
launch; higher = nagged less). Scout won't reopen the window more than
once every 6 hours, and only files that confidently match a bank's
format are ever touched — any other CSV in Downloads is ignored.

When downloading, grab the longest date range the bank offers when in
doubt: overlapping ranges are always safe (duplicates are skipped).

### Manual fallback

Any bank CSV can also be dropped into Budget → **Import bank CSVs** by
hand — same dedupe, same categories.

### Plaid (optional, currently parked)

The Plaid panel on the Budget page still works if production access is
ever granted; the saved keys are sandbox-only, which can't reach real
banks. Nothing needs to be done about it.

### Either way

**Categories:** fix any transaction's category right in the table. For
recurring fixes, add a keyword rule under Budget → Category rules (e.g.
anything containing `PELOTON` → Subscriptions) and hit Save — rules
reapply to everything, and the most specific keyword wins.

**Card payments don't double-count:** a Discover payment from KeyBank is
a transfer, not spending — the purchases on the card were already
counted. Scout files those under "Transfers & Payments" and excludes
them from spending math.

---

## Numbers to keep honest

- `STARTING_CAPITAL` in config.py — what the bot account began with.
- `R_DOLLARS` — dollars the bot risks per trade (1R). The bot caps
  premium at 3% of equity (~$300 on $10k) and the income bot's max risk
  is $500, so pick the figure that matches how you think about risk —
  adjustable live from the Trading page.
- The Phase 5 yardstick lives in the `BACKTEST` block.

## When something breaks

| Symptom | Fix |
|---|---|
| Desktop icon does nothing | Wait ~10 s on first open. Still nothing: run `launcher.ps1` in PowerShell and read the output. |
| `ModuleNotFoundError` | `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Trade log error on Overview | `credentials.json` must sit next to `app.py`; `SHEET_ID` must match the bot's config.py; the sheet must be shared with the service-account email. |
| Schwab page errors after working | The ~7-day login expired: `.venv\Scripts\python.exe schwab_login.py` |
| A CSV won't import | Scout names the columns it found — most likely the bank changed its export. The "Other" profiles handle any file with Date / Description / Amount columns. |
| Plaid sync fails for one bank | The bank wants a fresh login: run `plaid_link.py` again for that bank. Other errors name the cause (e.g. keys, environment mismatch). |
| Wrong category on lots of transactions | Budget → Category rules → add a keyword → Save rules & reapply. |

## Keep private

`config.py` (once keys are in it), `schwab_token.json`,
`credentials.json`, and `data/` (your transactions and Plaid tokens).
Never share, screenshot, or commit them. `.gitignore` already covers
all four.

---

*Dev notes: `assets/make_icon.py` regenerates the icon (needs pillow);
`assets/shoot.py` screenshots every page for visual checks (needs
selenium). Neither is needed to run Scout.*
