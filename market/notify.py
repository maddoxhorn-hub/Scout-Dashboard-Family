"""
Desktop notifications with zero extra packages.

Windows gets a system-tray balloon (built into .NET, present on every
Windows since 7); macOS gets a notification-center banner via osascript.
Both are fire-and-forget: a notification that fails to show must never
take the watcher down with it.
"""

import subprocess
import sys

_PS_BALLOON = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(10000, '{title}', '{message}', 'Info')
Start-Sleep -Seconds 12
$n.Dispose()
"""


def toast(title: str, message: str):
    title = str(title)[:60]
    message = str(message)[:240]
    try:
        if sys.platform == "win32":
            script = _PS_BALLOON.format(
                title=title.replace("'", "''"),
                message=message.replace("'", "''"),
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            def esc(text):
                return text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(
                ["osascript", "-e",
                 f'display notification "{esc(message)}" '
                 f'with title "{esc(title)}" sound name "Glass"'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass
