# Scout launcher -- starts the local server if needed, then opens Scout
# in its own app window. Run via "Scout Dashboard.vbs" (or the desktop
# shortcut) so no console window appears.

$ErrorActionPreference = 'SilentlyContinue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8501
$url  = "http://localhost:$port"

function Test-ScoutPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $port)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (-not (Test-ScoutPort)) {
    # One argument string with explicit quotes: the folder name contains a
    # space, and Start-Process does not quote array elements on its own.
    $serverArgs = "-m streamlit run `"$here\app.py`" --server.port $port " +
                  "--server.headless true --browser.gatherUsageStats false"
    Start-Process -WindowStyle Hidden `
        -FilePath "$here\.venv\Scripts\python.exe" `
        -ArgumentList $serverArgs `
        -WorkingDirectory $here

    # Wait for the server (up to ~30 s; first boot is the slow one)
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-ScoutPort) { break }
        Start-Sleep -Milliseconds 500
    }
}

# App-mode window (no tabs, no address bar) via Chrome -- Chrome on
# purpose: links clicked inside Scout open in the window's host browser,
# and Chrome is where the saved logins live. Edge is only a fallback.
$appBrowser = $null
foreach ($candidate in @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)) {
    if (Test-Path $candidate) { $appBrowser = $candidate; break }
}

if ($appBrowser) {
    Start-Process -FilePath $appBrowser -ArgumentList "--app=$url", "--window-size=1500,1000"
} else {
    Start-Process $url
}

# Bank-file pickup: if any bank's data is stale, open its download page in
# a separate window. Scout's watcher imports the CSVs and closes the window.
Start-Process -WindowStyle Hidden `
    -FilePath "$here\.venv\Scripts\pythonw.exe" `
    -ArgumentList "`"$here\bank_refresh.py`" --auto" `
    -WorkingDirectory $here
