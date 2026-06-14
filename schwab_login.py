"""
Connect (or reconnect) the dashboard to Schwab.

Run this in the dashboard folder:

    python schwab_login.py

A browser window opens. Log in with your regular Schwab brokerage
credentials -- not your developer-portal login -- approve, and pick the
account(s) to share. The login token is saved to schwab_token.json next
to this file.

Two things that look alarming but are normal:
  * The browser may warn about the connection to 127.0.0.1 not being
    private. That's this script's own temporary local page catching the
    redirect -- click Advanced and proceed.
  * Schwab expires these logins roughly every 7 days. When the dashboard
    says the token failed, just run this script again.

This script never trades. It only creates a login the dashboard uses to
READ balances and positions.
"""

import config


def main():
    if "PASTE_YOUR" in config.SCHWAB_API_KEY or "PASTE_YOUR" in config.SCHWAB_APP_SECRET:
        raise SystemExit(
            "Fill in SCHWAB_API_KEY and SCHWAB_APP_SECRET in config.py first.\n"
            "They come from your app at developer.schwab.com once its status\n"
            'is "Ready For Use" -- see SETUP.md, Part 2.'
        )

    # Make the login open in Chrome (saved passwords live there) -- the
    # schwab library uses Python's webbrowser module under the hood.
    try:
        import webbrowser

        from budget.downloads import _browser_path

        chrome = _browser_path()
        if chrome:
            webbrowser.register(
                "scout-browser", None,
                webbrowser.BackgroundBrowser(chrome), preferred=True,
            )
    except Exception:
        pass

    from schwab.auth import client_from_login_flow

    client_from_login_flow(
        config.SCHWAB_API_KEY,
        config.SCHWAB_APP_SECRET,
        config.SCHWAB_CALLBACK_URL,
        config.SCHWAB_TOKEN_PATH,
    )
    print()
    print(f"Login saved to {config.SCHWAB_TOKEN_PATH}.")
    print("Start the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
