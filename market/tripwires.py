"""
Tripwires -- plain, mechanical "is this move breaking?" tests.

Each wire asks one question about a watched ticker using only the
current quote, the previous check, and where the stock started. There
is no prediction here: a wire firing means "the move this pick depends
on is visibly bending," nothing more. A person (or, optionally, Claude)
judges whether it matters.

Every wire fires at most once per ticker per day, so a stock dancing
around a line doesn't ring the bell all afternoon.
"""

WIRES = {
    "move_against": "moved 2% against the thesis",
    "vwap_cross": "crossed the day's average price (VWAP) the wrong way",
    "gave_back": "gave back most of its move",
    "rsi_hook": "momentum (RSI) hooked back from an extreme",
}

# direction -> +1 means the pick needs the stock to go UP
_SIGN = {"call": 1, "up": 1, "put": -1, "down": -1}


def direction_sign(direction) -> int:
    return _SIGN.get(str(direction).lower(), 1)


def evaluate(item: dict, quote: dict, state: dict, today: str) -> list:
    """Run every wire for one ticker. Returns a list of alert dicts.

    item   {"symbol", "direction", "entry_price"}
    quote  one feed.quotes() value
    state  this ticker's persistent slot -- mutated in place; the caller
           saves it so restarts don't re-fire wires ("fired" holds
           wire-code -> date strings, "last_*" holds the previous check)
    """
    sign = direction_sign(item.get("direction"))
    close = quote.get("close")
    if not close:
        return []

    fired = state.setdefault("fired", {})
    prev_close = state.get("last_close")
    prev_rsi = state.get("last_rsi")
    word = "call" if sign > 0 else "put"
    alerts = []

    def fire(code, message):
        if fired.get(code) != today:
            fired[code] = today
            alerts.append({"symbol": item["symbol"], "code": code,
                           "message": message})

    # 1. Moved 2%+ against the thesis since it was picked.
    entry = item.get("entry_price")
    if entry:
        drift = (close - entry) / entry * 100 * sign
        if drift <= -2.0:
            fire("move_against",
                 f"{abs(drift):.1f}% against the {word} thesis "
                 f"(picked at {entry:,.2f}, now {close:,.2f})")

    # 2. Crossed VWAP against the thesis since the last check.
    vwap = quote.get("VWAP")
    if vwap and prev_close is not None:
        was_right_side = sign * (prev_close - vwap) >= 0
        now_wrong_side = sign * (close - vwap) < -0.001 * close
        if was_right_side and now_wrong_side:
            side = "below" if sign > 0 else "above"
            fire("vwap_cross",
                 f"crossed {side} VWAP ({vwap:,.2f}) -- the average "
                 f"buyer today is now {'underwater' if sign > 0 else 'ahead'}")

    # 3. Had a real move from the open and has given back 60%+ of it.
    cfo = quote.get("change_from_open")
    high, low = quote.get("high"), quote.get("low")
    if cfo is not None and high and low:
        open_price = close / (1 + cfo / 100) if cfo > -100 else None
        if open_price:
            peak = high if sign > 0 else low
            peak_move = (peak - open_price) * sign
            if peak_move / open_price >= 0.015:
                retraced = (peak - close) * sign
                if retraced >= 0.6 * peak_move:
                    fire("gave_back",
                         f"gave back {retraced / peak_move:.0%} of its "
                         f"{peak_move / open_price:+.1%} move from the open")

    # 4. RSI was at an extreme last check and has hooked back.
    rsi = quote.get("RSI")
    if rsi is not None and prev_rsi is not None:
        if sign > 0 and prev_rsi >= 70 and rsi <= 65:
            fire("rsi_hook", f"RSI fell {prev_rsi:.0f} → {rsi:.0f} from "
                             "overbought -- buyers easing off")
        if sign < 0 and prev_rsi <= 30 and rsi >= 35:
            fire("rsi_hook", f"RSI rose {prev_rsi:.0f} → {rsi:.0f} from "
                             "oversold -- sellers easing off")

    state["last_close"] = close
    state["last_rsi"] = rsi
    return alerts
