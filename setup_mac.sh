#!/bin/bash
# Scout setup for macOS -- one time only.
#
# How to run me (takes one paste into Terminal):
#   1. Open Terminal (press Cmd+Space, type Terminal, press Return)
#   2. Type:  bash
#      then a space, then drag THIS file into the Terminal window
#   3. Press Return and wait -- a "Scout Dashboard" icon lands on the
#      Desktop when it's done.

set -e
cd "$(dirname "$0")"
HERE="$(pwd)"

echo ""
echo "Setting up Scout in: $HERE"
echo ""

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys" >/dev/null 2>&1; then
  echo "This Mac needs Apple's developer tools first (they include Python)."
  echo "A dialog should appear -- click Install, wait for it to finish,"
  echo "then run this setup again the same way."
  xcode-select --install 2>/dev/null || true
  exit 1
fi

echo "Creating Scout's private Python environment (a few minutes)..."
python3 -m venv .venv
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

# Generate the double-clickable launcher locally so macOS trusts it and
# it knows this folder's location.
LAUNCHER="$HERE/Scout Dashboard.command"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
cd "$HERE"
PORT=8501
# A finished Scout update leaves this marker -- stop the old (detached) server
# so the next launch starts fresh and actually loads the new code. Closing the
# window alone never stops the server, so without this the update is invisible.
if [ -f ".scout_restart" ]; then
  rm -f ".scout_restart"
  pkill -f "streamlit run app.py" >/dev/null 2>&1 || true
  sleep 1
fi
if ! curl -s -o /dev/null --max-time 1 "http://127.0.0.1:\$PORT"; then
  nohup ./.venv/bin/python -m streamlit run app.py --server.port \$PORT \\
    --server.headless true --browser.gatherUsageStats false >/dev/null 2>&1 &
  for i in \$(seq 1 60); do
    curl -s -o /dev/null --max-time 1 "http://127.0.0.1:\$PORT" && break
    sleep 0.5
  done
fi
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "\$CHROME" ]; then
  "\$CHROME" --app="http://localhost:\$PORT" --window-size=1500,1000 >/dev/null 2>&1 &
else
  open "http://localhost:\$PORT"
fi
EOF
chmod +x "$LAUNCHER"

if [ -d "$HOME/Desktop" ]; then
  cp "$LAUNCHER" "$HOME/Desktop/Scout Dashboard.command"
  chmod +x "$HOME/Desktop/Scout Dashboard.command"
fi

echo ""
echo "Done! Double-click 'Scout Dashboard' on the Desktop to open Scout."
echo "(The same launcher also lives inside this folder.)"
