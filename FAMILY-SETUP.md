# Scout for the family

Scout is a small app that runs **entirely on your own computer**. Nothing
in it can touch a real bank or brokerage account — it only ever *reads* and
*practices*. Your information never leaves your machine.

What's inside:
- **Markets** — pick stocks you have a hunch about, watch them live, get a
  pop-up if a move turns around, and trade with **$100,000 of practice
  money** at real prices. Works the moment you open Scout — no setup.
- **Trainer** — a chart-reading practice game. You see a real (blinded)
  chart, call it *calls* or *puts*, and Scout grades you days later on what
  actually happened. Also works right away.
- **Budget** — see your spending in one place (optional; you choose how to
  feed it — see "Connecting your own accounts" below).
- **Links** — handy buttons, and the **Check for updates** button.

---

## Installing (one time)

First unzip **Scout-for-Family.zip**: double-click it, and you'll get a
**Scout Dashboard** folder. Put that folder somewhere permanent (Documents
is perfect), then follow your computer's section.

### Mac

1. Open the **Scout Dashboard** folder.
2. Open **Terminal**: press **Cmd+Space**, type `Terminal`, press Return.
   (One time only — you'll never need it again.)
3. In the Terminal window type `bash ` (the word and a space), then
   **drag the file `setup_mac.sh`** from the folder into the Terminal window
   and press **Return**.
4. Wait a few minutes. If the Mac offers to install "command line developer
   tools", click **Install**, let it finish, and repeat step 3.
5. When it says **Done!**, there's a **Scout Dashboard** icon on your
   Desktop. Double-click it. The first time the Mac may ask if you're sure —
   choose **Open**.

### Windows

1. Install Python: go to **python.org**, press the yellow **Download**
   button, run the installer, and **tick "Add python.exe to PATH"** at the
   bottom before clicking Install.
2. Open the **Scout Dashboard** folder and double-click
   **Setup (Windows).bat**. Wait for "Done!".
3. Double-click the new **Scout Dashboard** icon on your Desktop.

---

## Using the Markets tab

- **Watch a ticker**: type a symbol (AAPL, TSLA, DIS…), say whether your
  hunch is *Going up* or *Going down*, press **Watch**. While the market is
  open (9:30–4:00 New York time, weekdays) Scout checks it every minute.
- **Tripwires**: if a stock starts going against your hunch, a notification
  pops up and the alert appears in the feed.
- **Paper trading**: buy and sell with pretend money at real prices. The
  cards up top track how you're doing. Reset any time under
  "Trade history & account".

## Using the Trainer

Open **Trainer**, look at the chart, and press **Calls** or **Puts** with
how confident you are. Scout remembers your call and, using real history,
later tells you whether the move went your way. It's practice — there's no
real money and no penalty. Great for sharpening the read before you risk
anything live.

---

## Connecting your own accounts (optional)

Everything above works with **no accounts at all**. These are extras, and
they use **your own** logins — never anyone else's. Scout only ever gets
**read-only** access; it can't move money or place real trades.

- **Your spending (Budget):**
  - *Easiest:* download the CSV statement from your card/bank's website and
    import it on the Budget tab.
  - *Hands-off (advanced):* the Budget tab has a **Plaid** panel for live
    bank sync. It needs free developer keys from dashboard.plaid.com; paste
    them in, then press **Link a bank** and log in at your bank's secure
    page. (Ask whoever set this up for you if you want a hand — Plaid's setup
    is a little technical.)

- **Options practice with a brokerage feed (Alpaca):** if you want the
  options simulation, make a free **paper** account at alpaca.markets, copy
  its **paper** API keys, and paste them where Scout asks. Paper keys can
  only practice — they never touch real money.

Anything you paste in is stored **only on your computer** and is never
included if Scout is ever copied or updated.

---

## Keeping Scout up to date

When a newer version is published, Scout shows a small banner:
**"A newer Scout is ready."** To update:

1. Open the **Links** tab.
2. Under **Scout updates**, press **Check for updates**.
3. If there's a new one, press **Update now** and wait a few seconds.
4. Close the Scout window and open it again from the Desktop icon.

Updates only ever replace the **program**. Your keys, your linked banks,
your budget, your watchlist, and your practice trades are kept exactly as
they were — the updater is built so it can never touch them, and if anything
ever went wrong mid-update it puts everything back automatically.

---

Everything stays on your computer. Closing the window leaves Scout running
quietly in the background; restarting the computer stops it (the Desktop
icon brings it right back, with your watchlist and trades intact).
