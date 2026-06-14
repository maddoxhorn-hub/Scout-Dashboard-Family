"""
Trainer -- measure (and learn) Maddox's discretionary chart judgment.

Serves BLINDED real-historical chart snapshots: ticker hidden, future hidden,
but with his full indicator stack (Ripster EMA clouds, EMA 8/21, SMA 200,
session VWAP, volume, opening-range, premarket high/low, prior-day levels)
across the 2m / 10m / 1h timeframes. He labels each Bullish / Bearish / Pass
with a confidence; the call is scored against the hidden forward outcome and
logged. Over time this builds a dataset of his decisions -> his real hit rate,
calibration, and which conditions his good calls share.

This module is the engine: data, indicators, snapshot generation, the call
log, and analytics. The view (views/trainer.py) only renders what's stored
here, so a snapshot reveals nothing it shouldn't. Real prices via the saved
Alpaca data keys; nothing here trades anything.
"""

import datetime as dt
import json
import random
import statistics
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from market import alpaca_options

ET = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets/v2/stocks"
DIR = Path("data/trainer")               # PERSONAL: her calls + bar cache (never synced)
POOL_DIR = Path("trainer_pool")          # SHARED practice charts (ships + auto-updates)
SNAP_FILE = POOL_DIR / "snapshots.json"
CALLS_FILE = DIR / "calls.jsonl"
CACHE = DIR / "_bars"
# Shared-pool inputs. SEED = the trusted trader's reads, baked into a copy and
# weighted high (his data is the proven core). PARTNER = another trader's reads
# imported locally (e.g. carried over on the USB). Both feed the POOLED model
# alongside this machine's own calls; neither replaces her own track record.
SEED_FILE = POOL_DIR / "seed_calls.jsonl"
PARTNER_FILE = DIR / "partner_calls.jsonl"
SETTINGS_FILE = Path("data/market_settings.json")   # shared with the autopilot

OWN_WEIGHT = 1.0
SEED_WEIGHT = 3.0        # the trusted trader's reads count 3x in the pool
PARTNER_WEIGHT = 1.0

TF = {"2m": "2Min", "10m": "10Min", "1h": "1Hour"}
RIPSTER_PAIRS = [(8, 9), (5, 13), (34, 50), (72, 89), (180, 200)]   # hlc3 source
DISPLAY_BARS = {"2m": 80, "10m": 70, "1h": 60}
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "AMD", "META", "AMZN",
            "MSFT", "AVGO", "GOOGL", "NFLX", "COIN", "PLTR", "MU"]


# ----------------------------------------------------------------------
# Data (real bars via the saved Alpaca keys; cached per ticker/tf/window)
# ----------------------------------------------------------------------

def _headers():
    k = alpaca_options._keys()
    return {"APCA-API-KEY-ID": k.get("key", ""),
            "APCA-API-SECRET-KEY": k.get("secret", "")}


def _get(url):
    import time
    req = urllib.request.Request(url, headers=_headers())
    for a in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as exc:
            if "429" in str(exc) and a < 3:
                time.sleep(2 * (a + 1))
                continue
            raise


def bars(ticker, tf, start, end):
    """All bars (incl. premarket) for ticker/tf between ISO dates, cached.
    Each bar: {t: ET-aware datetime, o,h,l,c,v}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{ticker}_{tf}_{start}_{end}.json"
    if f.exists():
        raw = json.loads(f.read_text())
    else:
        out, token = [], None
        while True:
            q = {"timeframe": TF[tf], "start": start, "end": end,
                 "feed": "sip", "adjustment": "all", "limit": 10000}
            if token:
                q["page_token"] = token
            d = _get(f"{DATA}/{ticker}/bars?{urllib.parse.urlencode(q)}")
            out += d.get("bars") or []
            token = d.get("next_page_token")
            if not token:
                break
        raw = out
        f.write_text(json.dumps(raw))
    bars_ = []
    for b in raw:
        t = dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(ET)
        bars_.append({"t": t, "o": b["o"], "h": b["h"], "l": b["l"],
                      "c": b["c"], "v": b["v"]})
    return bars_


# ----------------------------------------------------------------------
# Indicators (computed only from bars at/before the snapshot time)
# ----------------------------------------------------------------------

def _ema(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _sma(vals, n):
    out = []
    for i in range(len(vals)):
        out.append(sum(vals[max(0, i - n + 1):i + 1]) / min(i + 1, n))
    return out


def _session_vwap(bs):
    """Anchored at each RTH 09:30; resets daily. None outside RTH-anchored run."""
    out, day, cum_pv, cum_v = [], None, 0.0, 0.0
    for b in bs:
        mins = b["t"].hour * 60 + b["t"].minute
        rth = 9 * 60 + 30 <= mins < 16 * 60
        if b["t"].date() != day:
            day, cum_pv, cum_v = b["t"].date(), 0.0, 0.0
        if rth:
            tp = (b["h"] + b["l"] + b["c"]) / 3
            cum_pv += tp * b["v"]
            cum_v += b["v"]
            out.append(cum_pv / cum_v if cum_v else None)
        else:
            out.append(None)
    return out


def _levels(all_bars, snap_day):
    """Key horizontal levels as of the snapshot day, from earlier sessions."""
    pri = [b for b in all_bars if b["t"].date() < snap_day]
    today_pre = [b for b in all_bars if b["t"].date() == snap_day
                 and (b["t"].hour * 60 + b["t"].minute) < 9 * 60 + 30]
    orb_bars = [b for b in all_bars if b["t"].date() == snap_day
                and 9 * 60 + 30 <= (b["t"].hour * 60 + b["t"].minute) < 9 * 60 + 45]
    lv = {}
    if pri:
        last_day = max(b["t"].date() for b in pri)
        pd_bars = [b for b in pri if b["t"].date() == last_day]
        lv["prior_day_high"] = max(b["h"] for b in pd_bars)
        lv["prior_day_low"] = min(b["l"] for b in pd_bars)
    if today_pre:
        lv["premarket_high"] = max(b["h"] for b in today_pre)
        lv["premarket_low"] = min(b["l"] for b in today_pre)
    if orb_bars:
        lv["orb_high"] = max(b["h"] for b in orb_bars)
        lv["orb_low"] = min(b["l"] for b in orb_bars)
    return lv


def _tf_payload(bs_full, snap_dt, tf):
    """Bars up to snap_dt + aligned indicators, trimmed to display window.
    Returns the dict the view renders (no future data)."""
    bs = [b for b in bs_full if b["t"] <= snap_dt]
    if len(bs) < 60:
        return None
    closes = [b["c"] for b in bs]
    hlc3 = [(b["h"] + b["l"] + b["c"]) / 3 for b in bs]
    clouds = [{"fast": _ema(hlc3, a), "slow": _ema(hlc3, b)} for a, b in RIPSTER_PAIRS]
    ema8, ema21, sma200 = _ema(closes, 8), _ema(closes, 21), _sma(closes, 200)
    vwap = _session_vwap(bs)
    n = DISPLAY_BARS[tf]
    sl = slice(-n, None)
    return {
        "bars": [{"t": b["t"].strftime("%Y-%m-%d %H:%M"), "o": b["o"], "h": b["h"],
                  "l": b["l"], "c": b["c"], "v": b["v"]} for b in bs[sl]],
        "ema8": ema8[sl], "ema21": ema21[sl], "sma200": sma200[sl],
        "vwap": vwap[sl],
        "clouds": [{"fast": c["fast"][sl], "slow": c["slow"][sl]} for c in clouds],
    }


# ----------------------------------------------------------------------
# Snapshot generation
# ----------------------------------------------------------------------

def _forward(daily_after, intraday_after, price_at_T):
    """Hidden outcomes: forward returns over several horizons + MFE/MAE."""
    out = {}
    # intraday horizons from 10m bars after T
    def ret_after(bars_after, minutes):
        if not bars_after:
            return None
        end = bars_after[0]["t"] + dt.timedelta(minutes=minutes)
        upto = [b for b in bars_after if b["t"] <= end]
        if not upto:
            return None
        return upto[-1]["c"] / price_at_T - 1
    out["fwd_2h"] = ret_after(intraday_after, 120)
    out["fwd_4h"] = ret_after(intraday_after, 240)
    # multi-day from daily closes after T
    if daily_after:
        out["fwd_1d"] = daily_after[0]["c"] / price_at_T - 1
        if len(daily_after) >= 3:
            out["fwd_3d"] = daily_after[2]["c"] / price_at_T - 1
        # MFE / MAE over next 3 sessions
        window = daily_after[:3]
        out["mfe_3d"] = max(b["h"] for b in window) / price_at_T - 1
        out["mae_3d"] = min(b["l"] for b in window) / price_at_T - 1
    return out


def generate(n=10, seed=None):
    """Build n blinded snapshots into the pool. Returns count added."""
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    pool = json.loads(SNAP_FILE.read_text()) if SNAP_FILE.exists() else []
    existing = {s["id"] for s in pool}
    added = 0
    attempts = 0
    while added < n and attempts < n * 6:
        attempts += 1
        ticker = rng.choice(UNIVERSE)
        # a random weekday in 2024-06 .. 2025-11 (option/intraday data present)
        day = dt.date(2024, 6, 1) + dt.timedelta(days=rng.randint(0, 520))
        if day.weekday() >= 5:
            continue
        snap_dt = dt.datetime.combine(
            day, dt.time(rng.randint(10, 14), rng.choice([0, 10, 20, 30, 40, 50])),
            tzinfo=ET)
        sid = f"{ticker}-{snap_dt:%Y%m%d-%H%M}"
        if sid in existing:
            continue
        try:
            b2 = bars(ticker, "2m", (day - dt.timedelta(days=5)).isoformat(),
                      (day + dt.timedelta(days=2)).isoformat())
            b10 = bars(ticker, "10m", (day - dt.timedelta(days=14)).isoformat(),
                       (day + dt.timedelta(days=2)).isoformat())
            b1h = bars(ticker, "1h", (day - dt.timedelta(days=55)).isoformat(),
                       (day + dt.timedelta(days=6)).isoformat())
            bd = bars(ticker, "1h", (day + dt.timedelta(days=1)).isoformat(),
                      (day + dt.timedelta(days=8)).isoformat())
        except Exception:
            continue
        tf_data = {}
        ok = True
        for tf, full in (("2m", b2), ("10m", b10), ("1h", b1h)):
            p = _tf_payload(full, snap_dt, tf)
            if p is None:
                ok = False
                break
            tf_data[tf] = p
        if not ok:
            continue
        at_T = [b for b in b10 if b["t"] <= snap_dt]
        if not at_T:
            continue
        price_T = at_T[-1]["c"]
        intraday_after = [b for b in b10 if b["t"] > snap_dt]
        # daily closes after T (collapse the post-day 1h bars into RTH-closes)
        daily_after = []
        post = sorted({b["t"].date() for b in bd if b["t"].date() > day})
        for dd in post[:4]:
            rth = [b for b in bd if b["t"].date() == dd
                   and (b["t"].hour * 60 + b["t"].minute) < 16 * 60]
            if rth:
                daily_after.append({"c": rth[-1]["c"], "h": max(x["h"] for x in rth),
                                    "l": min(x["l"] for x in rth)})
        outcomes = _forward(daily_after, intraday_after, price_T)
        if outcomes.get("fwd_2h") is None or outcomes.get("fwd_1d") is None:
            continue
        pool.append({
            "id": sid, "ticker": ticker, "snap_at": snap_dt.isoformat(),
            "price_at_T": price_T, "tf": tf_data,
            "levels": _levels(b10, day), "outcomes": outcomes,
        })
        existing.add(sid)
        added += 1
    SNAP_FILE.write_text(json.dumps(pool))
    return added


# ----------------------------------------------------------------------
# Calls + analytics
# ----------------------------------------------------------------------

# NOTE: the cache-key params are NOT underscore-prefixed on purpose -- Streamlit
# EXCLUDES underscore-named args from the cache key, which would (a) make all
# files share one cache entry (fatal once we load several call files for the
# pool) and (b) stop file edits from ever busting the cache. Plain names keep
# the key = (path, mtime, size), so each file caches separately and refreshes.
@st.cache_data(show_spinner=False)
def _load_pool(path, mtime, size):
    """Cached + crash-safe parse of a snapshots file. Keyed on (path, mtime,
    size) so a rewrite busts it and different files don't collide."""
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []          # corrupt or half-written -> don't crash the page


@st.cache_data(show_spinner=False)
def _load_calls(path, mtime, size):
    out = []
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue   # skip a half-written trailing line
    except OSError:
        pass
    return out


def pool():
    if not SNAP_FILE.exists():
        return []
    s = SNAP_FILE.stat()
    return _load_pool(str(SNAP_FILE), s.st_mtime, s.st_size)


def calls():
    if not CALLS_FILE.exists():
        return []
    s = CALLS_FILE.stat()
    return _load_calls(str(CALLS_FILE), s.st_mtime, s.st_size)


def _calls_from(path: Path):
    if not path.exists():
        return []
    s = path.stat()
    return _load_calls(str(path), s.st_mtime, s.st_size)


def seed_calls():
    """The trusted trader's reads shipped with this copy (may be empty)."""
    return _calls_from(SEED_FILE)


def partner_calls():
    """A partner's reads imported onto this machine (may be empty)."""
    return _calls_from(PARTNER_FILE)


def pool_enabled() -> bool:
    """Whether the shared pool (seed + partner) feeds the learning. Default on;
    harmless where no seed/partner exists (pool == own calls)."""
    try:
        s = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        return bool(s.get("trainer_use_pool", True)) if isinstance(s, dict) else True
    except (OSError, json.JSONDecodeError):
        return True


def set_pool_enabled(on: bool):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    s = {}
    try:
        loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            s = loaded
    except (OSError, json.JSONDecodeError):
        pass
    s["trainer_use_pool"] = bool(on)
    SETTINGS_FILE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def pool_sources():
    """Counts behind the pool, for honest UI: (own, seed, partner)."""
    return len(calls()), len(seed_calls()), len(partner_calls())


def answered_ids():
    return {c["id"] for c in calls()}


def next_unanswered():
    done = answered_ids()
    for s in pool():
        if s["id"] not in done:
            return s
    return None


HIT_MOVE = 0.03   # a "real" multi-day directional move (3% of price)


def grade(outcomes, label):
    """Multi-day, magnitude-aware scoring that matches holding a contract for
    days. Over the next ~3 sessions, take the favorable excursion (the high
    for a call, the low for a put) and the adverse one. It's a HIT only if the
    favorable move was BOTH meaningful (>= HIT_MOVE) AND larger than the
    adverse move; a MISS if the adverse side dominated by >= HIT_MOVE;
    otherwise CHOP (no decisive move — not scored, not a free pass).

    This is NOT more lenient than a 2h check — a pop that fades to a loss now
    counts MISS, and a flat chart counts CHOP. It just stops penalizing a call
    that dipped first and then ran (TSLA -2% at 2h, +26% by day 3 = a HIT)."""
    up = outcomes.get("mfe_3d")              # max % above entry over ~3d (>=0)
    if up is None:
        return "chop", 0.0
    down = -(outcomes.get("mae_3d") or 0.0)  # max % below entry over ~3d (>=0)
    fav, adv = (up, down) if label == "bull" else (down, up)
    if fav >= HIT_MOVE and fav > adv:
        return "hit", fav
    if adv >= HIT_MOVE and adv > fav:
        return "miss", -adv
    return "chop", 0.0


# ----------------------------------------------------------------------
# Setup features + pattern learning -- which setups she reads well vs badly,
# learned from her own scored calls. This is what turns the Trainer from a
# scoreboard into a system that recognizes (and explains) her patterns.
# ----------------------------------------------------------------------

def _last(seq):
    for v in reversed(seq or []):
        if v is not None:
            return v
    return None


# Plain-English label for each feature value (used in feedback + the patterns
# view). Each tuple's 2nd item is the value that FAVORS a bullish call.
FEATURE_TEXT = {
    "cloud_3450": {"bull": "a blue (bullish) 34/50 cloud", "bear": "an orange (bearish) 34/50 cloud"},
    "vs_vwap": {"above": "price above VWAP", "below": "price below VWAP"},
    "ema_stack": {"8>21": "EMA-8 above EMA-21", "8<21": "EMA-8 below EMA-21"},
    "short_trend": {"rising": "the short-term trend rising", "falling": "the short-term trend falling"},
    "regime": {"above200": "trading above the 1h 200-SMA", "below200": "trading below the 1h 200-SMA"},
}
# (feature, value-that-favors-a-bull-call)
_BULL_SIDE = {"cloud_3450": "bull", "vs_vwap": "above", "ema_stack": "8>21",
              "short_trend": "rising", "regime": "above200"}


def setup_features(snap):
    """The conditions present AT the decision moment -- the 'setup fingerprint'.
    Computed only from the stored snapshot bars/indicators (no future data)."""
    f = {}
    tf = snap.get("tf", {})
    m = tf.get("10m") or tf.get("2m")
    if m and m.get("bars"):
        close = m["bars"][-1]["c"]
        vwap = _last(m.get("vwap"))
        ema8, ema21 = _last(m.get("ema8")), _last(m.get("ema21"))
        clouds = m.get("clouds") or []
        if len(clouds) >= 3:                       # clouds[2] == the 34/50 cloud
            cf, cs = _last(clouds[2].get("fast")), _last(clouds[2].get("slow"))
            if cf is not None and cs is not None:
                f["cloud_3450"] = "bull" if cf >= cs else "bear"
        if vwap is not None:
            f["vs_vwap"] = "above" if close >= vwap else "below"
        if ema8 is not None and ema21 is not None:
            f["ema_stack"] = "8>21" if ema8 >= ema21 else "8<21"
        e8 = [v for v in (m.get("ema8") or [])[-10:] if v is not None]
        if len(e8) >= 2:
            f["short_trend"] = "rising" if e8[-1] >= e8[0] else "falling"
        lv = snap.get("levels", {})
        if lv and close:
            near, best = "open_space", 0.008       # "near" a level == within 0.8%
            for k, v in lv.items():
                d = abs(close - v) / close
                if d < best:
                    best, near = d, k
            f["near_level"] = near
    h = tf.get("1h")
    if h and h.get("bars"):
        hs = _last(h.get("sma200"))
        if hs is not None:
            f["regime"] = "above200" if h["bars"][-1]["c"] >= hs else "below200"
    return f


def _pool_index():
    return {s["id"]: s for s in pool()}


def _call_features(row, index):
    """Stored fingerprint, or recomputed from the snapshot for older calls."""
    if row.get("setup"):
        return row["setup"]
    s = index.get(row["id"])
    return setup_features(s) if s else {}


def _signature_text(label, feat):
    """The strategy's core combo: direction + Ripster cloud + VWAP position."""
    dir_txt = "calls" if label == "bull" else "puts"
    bits = []
    if "cloud_3450" in feat:
        bits.append("a blue cloud" if feat["cloud_3450"] == "bull" else "an orange cloud")
    if "vs_vwap" in feat:
        bits.append("above VWAP" if feat["vs_vwap"] == "above" else "below VWAP")
    return f"{dir_txt} on {' '.join(bits)}" if bits else dir_txt


def _scored_rows(pooled=None):
    """Decisive (hit/miss) directional calls as (call, features, weight). With
    the pool on, adds the trusted seed (weight SEED_WEIGHT) and any imported
    partner calls (PARTNER_WEIGHT) next to this machine's own (OWN_WEIGHT)."""
    if pooled is None:
        pooled = pool_enabled()
    index = _pool_index()
    out = []

    def add(rows, weight):
        for c in rows:
            if c.get("label") in ("bull", "bear") and c.get("correct") is not None:
                out.append((c, _call_features(c, index), weight))

    add(calls(), OWN_WEIGHT)
    if pooled:
        add(seed_calls(), SEED_WEIGHT)
        add(partner_calls(), PARTNER_WEIGHT)
    return out


def patterns(min_n=3, pooled=None):
    """Which setups are read well vs badly. Hit rates are WEIGHTED toward the
    trusted seed (his reads count 3x); the sample gate uses the RAW count so a
    thin history can't fire. Strongest/weakest signatures (raw n >= min_n)."""
    rows = _scored_rows(pooled)
    out = {"n": len(rows), "by_feature": {}, "strong": [], "weak": [],
           "pooled": pool_enabled() if pooled is None else pooled}
    if not rows:
        return out
    for key in ("cloud_3450", "vs_vwap", "ema_stack", "short_trend", "regime"):
        vals = {}
        for c, feat, w in rows:
            if key in feat:
                d = vals.setdefault(feat[key], {"wc": 0.0, "w": 0.0, "n": 0})
                d["wc"] += w * (1 if c["correct"] else 0)
                d["w"] += w
                d["n"] += 1
        kept = {v: {"n": d["n"], "acc": d["wc"] / d["w"]}
                for v, d in vals.items() if d["n"] >= min_n}
        if kept:
            out["by_feature"][key] = kept
    sig = {}
    for c, feat, w in rows:
        k = (c["label"], feat.get("cloud_3450"), feat.get("vs_vwap"))
        d = sig.setdefault(k, {"text": _signature_text(c["label"], feat),
                               "wc": 0.0, "w": 0.0, "n": 0})
        d["wc"] += w * (1 if c["correct"] else 0)
        d["w"] += w
        d["n"] += 1
    scored = [{"text": d["text"], "n": d["n"], "acc": d["wc"] / d["w"]}
              for d in sig.values() if d["n"] >= min_n]
    out["strong"] = sorted((s for s in scored if s["acc"] >= 0.60),
                           key=lambda s: (-s["acc"], -s["n"]))
    out["weak"] = sorted((s for s in scored if s["acc"] < 0.45),
                         key=lambda s: (s["acc"], -s["n"]))
    return out


def explain(row):
    """Plain-English 'why' for one graded call: which conditions were for vs
    against the call, plus her track record on that exact signature."""
    feat = row.get("setup") or _call_features(row, _pool_index())
    if row["label"] not in ("bull", "bear") or not feat:
        return None
    bullish_call = row["label"] == "bull"
    aligned, against = [], []
    for key, bull_val in _BULL_SIDE.items():
        if key not in feat:
            continue
        favors_bull = feat[key] == bull_val
        txt = FEATURE_TEXT[key][feat[key]]
        (aligned if favors_bull == bullish_call else against).append(txt)
    mysig = (row["label"], feat.get("cloud_3450"), feat.get("vs_vwap"))
    wc = w = 0.0
    n = 0
    for c, cf, weight in _scored_rows():     # pooled + weighted per the setting
        if (c["label"], cf.get("cloud_3450"), cf.get("vs_vwap")) == mysig:
            wc += weight * (1 if c["correct"] else 0)
            w += weight
            n += 1
    rate = {"n": n, "acc": (wc / w) if w else None}
    return {"aligned": aligned, "against": against,
            "signature": _signature_text(row["label"], feat), "rate": rate}


# ----------------------------------------------------------------------
# Live edge lookup -- lets the paper autopilot weigh a real setup by what
# the owner's own reads have learned (their discretionary edge, made mechanical).
# Per-user + local: reads only this machine's calls; nothing is uploaded.
# ----------------------------------------------------------------------

EDGE_MIN_N = 5          # need this many similar past calls before acting
BLINDSPOT_ACC = 0.35    # at/below this (with enough samples) -> skip the trade
WEAK_ACC = 0.45         # below this -> half size
EDGE_ACC = 0.60         # at/above this -> a proven edge


def _live_snapshot(ticker, now):
    """A feature-only snapshot for a LIVE symbol as of `now` (no future data)."""
    ticker = str(ticker).split(":")[-1].strip().upper()   # NASDAQ:NVDA -> NVDA
    today = now.date()
    b10 = bars(ticker, "10m", (today - dt.timedelta(days=6)).isoformat(),
               (today + dt.timedelta(days=1)).isoformat())
    p10 = _tf_payload(b10, now, "10m")
    if p10 is None:
        return None
    tf = {"10m": p10}
    b1h = bars(ticker, "1h", (today - dt.timedelta(days=60)).isoformat(),
               (today + dt.timedelta(days=1)).isoformat())
    p1h = _tf_payload(b1h, now, "1h")
    if p1h is not None:
        tf["1h"] = p1h
    return {"tf": tf, "levels": _levels(b10, today)}


def live_setup_edge(ticker, direction, now=None):
    """What the owner's reads have learned about THIS live setup. Computes the
    setup fingerprint and looks up their hit rate on the matching signature.
    Returns {verdict, signature, n, acc}; verdict is 'blindspot' | 'weak' |
    'neutral' | 'edge' | 'unknown'. Never raises -- 'unknown' on any problem."""
    label = "bull" if str(direction).lower() == "call" else "bear"
    out = {"verdict": "unknown", "signature": None, "n": 0, "acc": None}
    if not alpaca_options.configured():
        return out                          # no data keys -> no signal
    try:
        snap = _live_snapshot(ticker, now or dt.datetime.now(ET))
        if not snap:
            return out
        feat = setup_features(snap)
        sig = (label, feat.get("cloud_3450"), feat.get("vs_vwap"))
        out["signature"] = _signature_text(label, feat)
        wc = w = 0.0
        n = 0
        for c, cf, weight in _scored_rows():     # pooled + weighted per the setting
            if (c["label"], cf.get("cloud_3450"), cf.get("vs_vwap")) == sig:
                wc += weight * (1 if c["correct"] else 0)
                w += weight
                n += 1
        out["n"] = n
        if n >= EDGE_MIN_N:
            acc = wc / w
            out["acc"] = acc
            out["verdict"] = ("blindspot" if acc <= BLINDSPOT_ACC
                              else "weak" if acc < WEAK_ACC
                              else "edge" if acc >= EDGE_ACC else "neutral")
    except Exception:
        return {"verdict": "unknown", "signature": None, "n": 0, "acc": None}
    return out


def _sharing_rows(source):
    """This machine's scored calls trimmed to the learning signal only (label,
    confidence, correct, setup) -- not the full personal log. Features baked in
    so the receiving copy needs no snapshot pool."""
    index = _pool_index()
    rows = []
    for c in calls():
        if c.get("label") not in ("bull", "bear") or c.get("correct") is None:
            continue
        rows.append({"id": c.get("id"), "label": c["label"],
                     "confidence": c.get("confidence"), "correct": c["correct"],
                     "setup": _call_features(c, index), "source": source})
    return rows


def calls_for_sharing(source="partner") -> str:
    """JSONL text of this machine's reads, for a download/USB hand-off."""
    return "\n".join(json.dumps(r) for r in _sharing_rows(source))


def export_seed(out_path, source="seed"):
    """Write this machine's reads as a SEED file (weighted high) for other
    copies to learn from. Returns the count written."""
    rows = _sharing_rows(source)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return len(rows)


def import_partner_calls(src_path, source="partner"):
    """Bring another trader's scored calls onto THIS machine (e.g. carried over
    on the USB) so the pool can learn from them at PARTNER_WEIGHT. Returns the
    count imported. Their data stays local; nothing is uploaded."""
    rows = []
    for line in Path(src_path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        if c.get("label") in ("bull", "bear") and c.get("correct") is not None:
            c["source"] = source
            rows.append(c)
    PARTNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PARTNER_FILE.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    try:
        _load_calls.clear()        # show the imported data immediately
    except Exception:
        pass
    return len(rows)


def record(snap, label, confidence):
    """Log a call and score it against the hidden multi-day outcome."""
    DIR.mkdir(parents=True, exist_ok=True)
    o = snap["outcomes"]
    g, fav = ("chop", 0.0)
    correct = None
    if label in ("bull", "bear"):
        g, fav = grade(o, label)
        correct = True if g == "hit" else (False if g == "miss" else None)
    row = {"id": snap["id"], "ticker": snap["ticker"],
           "at": dt.datetime.now(ET).isoformat(timespec="seconds"),
           "label": label, "confidence": confidence, "grade": g,
           "fav_move": fav,
           "setup": setup_features(snap),   # the fingerprint -> pattern learning
           "mfe_3d": o.get("mfe_3d"), "mae_3d": o.get("mae_3d"),
           "fwd_2h": o.get("fwd_2h"), "fwd_1d": o.get("fwd_1d"),
           "fwd_3d": o.get("fwd_3d"), "correct": correct}
    with CALLS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def analytics():
    c = calls()
    dir_calls = [x for x in c if x["label"] in ("bull", "bear")]
    directional = [x for x in dir_calls if x["correct"] is not None]   # hit/miss only
    out = {"total": len(c), "passes": sum(1 for x in c if x["label"] == "pass"),
           "chop": len(dir_calls) - len(directional), "directional": len(directional)}
    if directional:
        wins = sum(1 for x in directional if x["correct"])
        out["accuracy"] = wins / len(directional)
        # by confidence
        byc = {}
        for x in directional:
            byc.setdefault(x["confidence"], []).append(x["correct"])
        out["by_confidence"] = {k: sum(v) / len(v) for k, v in sorted(byc.items())}
        # high-confidence (4-5) subset
        hi = [x for x in directional if x["confidence"] >= 4]
        out["high_conf_n"] = len(hi)
        out["high_conf_acc"] = (sum(1 for x in hi if x["correct"]) / len(hi)) if hi else None
        # rough 95% CI on overall accuracy
        n, p = len(directional), out["accuracy"]
        se = (p * (1 - p) / n) ** 0.5
        out["ci"] = (max(0, p - 1.96 * se), min(1, p + 1.96 * se))
    return out
