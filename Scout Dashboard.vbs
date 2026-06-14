' Opens Scout silently (no console flash). The desktop shortcut points here.
Set sh = CreateObject("WScript.Shell")
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & folder & "\launcher.ps1""", 0, False
