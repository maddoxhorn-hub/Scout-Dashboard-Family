"""
Link a bank to Scout through Plaid -- run once per bank.

    .venv\\Scripts\\python.exe plaid_link.py

A browser opens with Plaid's secure Link flow. Pick the bank (Discover,
American Express, KeyBank, ...), log in THERE -- your bank credentials go
to Plaid, never to Scout -- and approve. The read-only access token is
saved to data/plaid_tokens.json on this machine.

Run it again to add the next bank. After linking, the Budget page gets a
"Sync" button that pulls new transactions any time you press it.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import config
from budget import downloads, plaid_sync

PORT = 8123

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Scout · Link a bank</title>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
</head>
<body style="font-family:-apple-system,Segoe UI,sans-serif;background:#F5F5F7;
             display:grid;place-items:center;height:100vh;margin:0;color:#1D1D1F">
<div style="text-align:center">
  <div style="font-size:22px;font-weight:700">Scout</div>
  <div id="msg" style="margin-top:8px;color:#6E6E73">Opening Plaid&hellip;</div>
</div>
<script>
const handler = Plaid.create({
  token: "__LINK_TOKEN__",
  onSuccess: async (public_token, metadata) => {
    document.getElementById('msg').textContent = "Finishing the link…";
    const institution = metadata.institution ? metadata.institution.name : "Bank";
    const r = await fetch('/exchange', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({public_token, institution})
    });
    document.getElementById('msg').textContent = r.ok
      ? institution + " linked — you can close this tab. Run plaid_link.py again to add another bank."
      : "Something went wrong — check the terminal window.";
  },
  onExit: (err) => {
    document.getElementById('msg').textContent =
      "Plaid closed without linking." + (err && err.display_message ? " " + err.display_message : "");
  }
});
handler.open();
</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    link_token = ""
    done = threading.Event()
    result = {}

    def do_GET(self):
        page = _PAGE.replace("__LINK_TOKEN__", self.link_token)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def do_POST(self):
        if self.path != "/exchange":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        try:
            data = plaid_sync._post(
                "/item/public_token/exchange",
                {"public_token": body["public_token"]},
            )
            plaid_sync.save_item(
                body.get("institution", "Bank"),
                data["access_token"],
                data["item_id"],
            )
            _Handler.result = {"institution": body.get("institution", "Bank")}
            self.send_response(200)
            self.end_headers()
        except Exception as exc:
            _Handler.result = {"error": str(exc)}
            self.send_response(500)
            self.end_headers()
        _Handler.done.set()

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main():
    if not plaid_sync.keys_configured():
        raise SystemExit(
            "Fill in the Plaid keys first -- easiest from Scout's Budget "
            "page\n(Plaid panel), or paste them into config.py.\n"
            "They're at dashboard.plaid.com -> Developers -> Keys."
        )

    if config.PLAID_ENV == "sandbox":
        print()
        print("NOTE: these are SANDBOX keys -- only Plaid's fake practice")
        print("banks will appear here, not your real accounts. To link real")
        print("banks, save the production secret on Scout's Budget page.")
        print()

    print("Creating a Plaid Link session…")
    data = plaid_sync._post("/link/token/create", {
        "client_name": "Scout",
        "user": {"client_user_id": "scout-local"},
        "products": ["transactions"],
        "transactions": {"days_requested": 730},
        "country_codes": ["US"],
        "language": "en",
    })
    _Handler.link_token = data["link_token"]

    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    print(f"Opening {url} — pick your bank and log in there.")
    downloads.open_url(url)  # Chrome, where the bank logins live

    if not _Handler.done.wait(timeout=600):
        server.shutdown()
        raise SystemExit("Timed out after 10 minutes — run plaid_link.py again.")
    server.shutdown()

    if "error" in _Handler.result:
        raise SystemExit(f"Link failed: {_Handler.result['error']}")

    institution = _Handler.result["institution"]
    print()
    print(f"{institution} linked ✓  (saved to {config.PLAID_TOKENS_PATH})")
    print("Open Scout → Budget → Sync to pull transactions,")
    print("or run plaid_link.py again to link another bank.")


if __name__ == "__main__":
    main()
