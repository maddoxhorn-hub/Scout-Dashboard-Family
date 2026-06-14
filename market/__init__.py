"""
Markets -- live watching and paper trading.

feed       quotes from TradingView's public screener + the NYSE calendar
tripwires  mechanical "this move is breaking" tests, no prediction
watchlist  today's scan picks merged with hand-added tickers
paper      practice-money ledger, real prices
notify     desktop notifications (Windows balloon / macOS banner)
watcher    the once-a-minute background loop that ties it together

Like the rest of Scout: read-only against the real world. Nothing in
this package can place an order or move a dollar.
"""
