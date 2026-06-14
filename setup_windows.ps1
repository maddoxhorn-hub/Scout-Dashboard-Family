# Scout setup for Windows -- one time only. Run via "Setup (Windows).bat".

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "Setting up Scout in: $here"
Write-Host ""

# --- find Python 3 ------------------------------------------------------
$py = $null
try { if ((& py -3 --version 2>$null) -match 'Python 3') { $py = 'py' } } catch {}
if (-not $py) {
    try { if ((& python --version 2>$null) -match 'Python 3') { $py = 'python' } } catch {}
}
if (-not $py) {
    Write-Host "Python isn't installed yet." -ForegroundColor Yellow
    Write-Host "Go to python.org, press the big Download button, run the"
    Write-Host "installer, and TICK the 'Add python.exe to PATH' box at the"
    Write-Host "bottom. Then double-click this setup again."
    exit 1
}

# --- private environment + packages --------------------------------------
if (-not (Test-Path "$here\.venv\Scripts\python.exe")) {
    Write-Host "Creating Scout's private Python environment (a few minutes)..."
    if ($py -eq 'py') { & py -3 -m venv "$here\.venv" }
    else { & python -m venv "$here\.venv" }
}
& "$here\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$here\.venv\Scripts\python.exe" -m pip install --quiet -r "$here\requirements.txt"

# --- desktop shortcut -----------------------------------------------------
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$desktop\Scout Dashboard.lnk")
$shortcut.TargetPath = "$env:WINDIR\System32\wscript.exe"
$shortcut.Arguments = "`"$here\Scout Dashboard.vbs`""
$shortcut.WorkingDirectory = $here
if (Test-Path "$here\assets\scout.ico") {
    $shortcut.IconLocation = "$here\assets\scout.ico"
}
$shortcut.Save()

Write-Host ""
Write-Host "Done! Double-click 'Scout Dashboard' on the Desktop to open Scout." -ForegroundColor Green
