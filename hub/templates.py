"""Generated pages and scripts served by the hub.

Why this is a separate module
-----------------------------
Every value that ends up inside a generated PowerShell script or HTML page goes
through one of the helpers below.

* The old ``_escape_powershell`` replaced ``"`` with ``\\`"`` and *then* doubled
  every backtick, which turned the escape into a literal backtick followed by a
  bare quote, so a crafted ``hub_url`` could break out of the string. Values are
  now validated against a strict URL pattern and embedded in single-quoted
  PowerShell strings (the only escape needed there is doubling ``'``).
* The mobile page injected the hub URL into HTML unescaped (reflected XSS). It is
  now HTML-escaped and URL-encoded where appropriate.

The installer also follows the project's ground rules: it is *visible* (a tray
icon, no hidden windows) and it asks for explicit consent before installing.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from typing import Iterable, List

_URL_RE = re.compile(r"^https?://[A-Za-z0-9._\-]+(?::\d{1,5})?$")
_IPV6_URL_RE = re.compile(r"^https?://\[[0-9A-Fa-f:.]+\](?::\d{1,5})?$")


def is_safe_base_url(url: str) -> bool:
    """Only ``http(s)://host[:port]`` with a conservative character set (no path/query)."""
    url = (url or "").strip().rstrip("/")
    return bool(_URL_RE.match(url) or _IPV6_URL_RE.match(url))


def clean_base_urls(urls: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for url in urls:
        url = (url or "").strip().rstrip("/")
        if url and is_safe_base_url(url) and url not in seen:
            seen.append(url)
    return seen


def _ps_quote(value: str) -> str:
    """Single-quoted PowerShell literal. Inside '...' nothing expands; only ' needs doubling."""
    return "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Windows installer
# --------------------------------------------------------------------------- #
_WINDOWS_INSTALLER = r"""# Himaya - Windows enrollment
# Run in a normal PowerShell window on the computer you want to protect.
# Administrator rights are NOT required.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Candidates = @(@@CANDIDATES@@)
$AgentDir   = Join-Path $env:LOCALAPPDATA 'HimayaAgent'

function Write-Step([string]$Text) { Write-Host ''; Write-Host ('==> ' + $Text) -ForegroundColor Cyan }

function Find-Python {
    foreach ($name in @('python', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($name -eq 'py') { $exe = (& py -3 -c 'import sys; print(sys.executable)' 2>$null) }
            else { $exe = (& $cmd.Source -c 'import sys; print(sys.executable)' 2>$null) }
            if ($exe) {
                $exe = ([string]$exe).Trim()
                if ($exe -and (Test-Path $exe)) {
                    $ok = (& $exe -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)' 2>$null)
                    if (([string]$ok).Trim() -eq '1') { return $exe }
                }
            }
        } catch { }
    }
    return $null
}

try {
    Write-Host ''
    Write-Host '  Himaya device protection' -ForegroundColor Cyan
    Write-Host '  ------------------------'
    Write-Host '  This installs a small program on THIS computer. It is always visible:'
    Write-Host '  a "Himaya active" icon stays in the system tray while it runs.'
    Write-Host ''
    Write-Host '  What it does:'
    Write-Host '    * Reports that this computer is online, and warns you if a VPN app is started.'
    Write-Host '    * Lets the parent lock the screen, send a message, or pause the internet.'
    Write-Host '    * Blocks the websites the parent chooses.'
    Write-Host '    * Child computers only: takes a screenshot every few minutes and sends it'
    Write-Host '      to YOUR hub (nowhere else).'
    Write-Host '  What it never does: record keystrokes, use the camera or microphone,'
    Write-Host '  or read private messages.'
    Write-Host ''

    $who = (Read-Host '  Is this computer used by a child or an adult? [child/adult] (default: child)').Trim().ToLower()
    if ($who -eq '') { $who = 'child' }
    if ($who -ne 'child' -and $who -ne 'adult') { throw 'Please answer "child" or "adult".' }
    if ($who -eq 'adult') {
        Write-Host '  Adult computers: no screenshots are taken by default. Only install this with the adult''s agreement.' -ForegroundColor Yellow
    }
    $consent = (Read-Host '  Does the person who uses this computer know about this? Type YES to continue').Trim().ToLower()
    if ($consent -ne 'yes') { throw 'Setup cancelled. Nothing was installed.' }

    Write-Step 'Checking for Python'
    $py = Find-Python
    if (-not $py) {
        throw ('Python 3.9 or newer was not found. Install it first (for example: winget install -e --id Python.Python.3.12), ' +
               'open a NEW PowerShell window, and run this command again.')
    }
    $pyw = Join-Path (Split-Path $py -Parent) 'pythonw.exe'
    if (-not (Test-Path $pyw)) { $pyw = $py }
    Write-Host ('    using ' + $py)

    Write-Step 'Looking for your Himaya hub'
    $hub = $null
    foreach ($c in $Candidates) {
        try {
            $r = Invoke-RestMethod -Uri ($c + '/health') -TimeoutSec 4
            if ($r.status -eq 'ok') { $hub = $c; break }
        } catch { }
    }
    if (-not $hub) {
        throw 'Could not reach the Himaya hub. Is this computer on the same Wi-Fi as the hub? (Or use the Internet link from the dashboard.)'
    }
    Write-Host ('    found ' + $hub)

    Write-Step 'Pairing'
    $pin = (Read-Host '  Enter the 6-digit PIN shown on the Enroll page of the Himaya dashboard').Trim()
    if ($pin -notmatch '^\d{6}$') { throw 'The PIN must be exactly 6 digits.' }
    $computer = $env:COMPUTERNAME; if (-not $computer) { $computer = 'Windows PC' }
    $account = $env:USERNAME; if (-not $account) { $account = 'user' }
    $deviceName = $computer + ' (' + $account + ')'
    $body = @{ pin = $pin; name = $deviceName; platform = 'windows'; owner_type = $who } | ConvertTo-Json -Compress
    try {
        $pair = Invoke-RestMethod -Uri ($hub + '/enroll/pair') -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 20
    } catch {
        $code = 0
        try { $code = [int]$_.Exception.Response.StatusCode } catch { }
        if ($code -eq 403) { throw 'That PIN was not accepted. The PIN changes after every use - check the dashboard and try again.' }
        if ($code -eq 429) { throw 'Too many wrong PINs. Wait a few minutes, then try again.' }
        throw ('Pairing failed: ' + $_.Exception.Message)
    }
    if (-not $pair.agent_key -or -not $pair.device_id) { throw 'The hub did not return pairing details. Update the hub and try again.' }

    Write-Step 'Installing the agent'
    # Stop an older copy first (re-install).
    try {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like '*himaya_windows_agent.py*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch { }
    New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null
    $agentPath = Join-Path $AgentDir 'himaya_windows_agent.py'
    Invoke-WebRequest -Uri ($hub + '/enroll/win/agent.py') -OutFile $agentPath -UseBasicParsing
    Invoke-WebRequest -Uri ($hub + '/enroll/win/uninstall.ps1') -OutFile (Join-Path $AgentDir 'uninstall.ps1') -UseBasicParsing
    if ((Get-Item $agentPath).Length -lt 2000) { throw 'The agent download looks incomplete. Try again.' }

    $config = [ordered]@{
        hub_url        = $hub
        candidate_urls = @($Candidates)
        device_id      = $pair.device_id
        device_name    = $deviceName
        agent_key      = $pair.agent_key
        owner_type     = $who
    }
    ($config | ConvertTo-Json) | Set-Content -Path (Join-Path $AgentDir 'agent_config.json') -Encoding UTF8

    Write-Host '    installing Python packages (requests, pillow, pystray)...'
    & $py -m pip install --user --quiet --disable-pip-version-check requests pillow pystray
    if ($LASTEXITCODE -ne 0) { throw 'Installing the Python packages failed. Check your internet connection and try again.' }

    Write-Step 'Starting automatically at sign-in'
    $startup = [Environment]::GetFolderPath('Startup')
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $startup 'Himaya Agent.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = '"' + $agentPath + '"'
    $lnk.WorkingDirectory = $AgentDir
    $lnk.Description = 'Himaya family safety agent (visible in the system tray)'
    $lnk.Save()

    Start-Process -FilePath $pyw -ArgumentList ('"' + $agentPath + '"') -WorkingDirectory $AgentDir

    Write-Host ''
    Write-Host '  Done. Look for the Himaya icon in the system tray (near the clock).' -ForegroundColor Green
    Write-Host ('  This computer is now listed in your dashboard as: ' + $deviceName)
    Write-Host '  To remove Himaya later:'
    Write-Host ('    powershell -ExecutionPolicy Bypass -File "' + (Join-Path $AgentDir 'uninstall.ps1') + '"')
    Write-Host ''
} catch {
    Write-Host ''
    Write-Host ('  Himaya setup stopped: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ''
}
"""


def build_windows_installer(candidate_urls: Iterable[str]) -> str:
    urls = clean_base_urls(candidate_urls)
    if not urls:
        raise ValueError("no safe hub URL to embed in the installer")
    return _WINDOWS_INSTALLER.replace("@@CANDIDATES@@", ", ".join(_ps_quote(u) for u in urls))


_WINDOWS_UNINSTALLER = r"""# Himaya - Windows uninstall
# Removes the Himaya agent from this computer. The hub is told, so the parent sees it in the activity feed.
$ErrorActionPreference = 'Continue'
$dir = Join-Path $env:LOCALAPPDATA 'HimayaAgent'
$cfgPath = Join-Path $dir 'agent_config.json'
$cfg = $null
if (Test-Path $cfgPath) { try { $cfg = Get-Content -Raw -Path $cfgPath | ConvertFrom-Json } catch { } }

if ($cfg -and $cfg.agent_key) {
    try {
        $body = @{ type = 'agent_stopped'; data = @{ reason = 'uninstalled'; by = $env:USERNAME } } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri (([string]$cfg.hub_url).TrimEnd('/') + '/agents/' + $cfg.device_id + '/event') -Method Post `
            -Headers @{ 'X-API-Key' = $cfg.agent_key } -ContentType 'application/json' -Body $body -TimeoutSec 6 | Out-Null
        Write-Host 'Told the hub that Himaya was removed.'
    } catch { Write-Host 'Could not reach the hub to report the removal (continuing).' }
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*himaya_windows_agent.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Himaya Agent.lnk'
if (Test-Path $lnk) { Remove-Item $lnk -Force }

# Undo the per-user "pause internet" setting if the agent left it on.
try {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    $p = Get-ItemProperty -Path $key -ErrorAction Stop
    if ($p.ProxyServer -eq '127.0.0.1:9') {
        Set-ItemProperty -Path $key -Name ProxyEnable -Value 0
        Remove-ItemProperty -Path $key -Name ProxyServer -ErrorAction SilentlyContinue
        Write-Host 'Restored internet settings.'
    }
} catch { }

# Remove the website block list from the hosts file (only possible as Administrator).
try {
    $hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
    $text = Get-Content -Raw -Path $hosts
    if ($text -match '# HIMAYA BLOCKLIST START') {
        $clean = [regex]::Replace($text, '(?s)\r?\n?# HIMAYA BLOCKLIST START.*?# HIMAYA BLOCKLIST END\r?\n?', "`r`n")
        Set-Content -Path $hosts -Value $clean -Encoding ASCII
        Write-Host 'Removed the website block list from the hosts file.'
    }
} catch { Write-Host 'To remove the website block list, run this script again as Administrator.' -ForegroundColor Yellow }

if (Test-Path $dir) { Start-Sleep -Milliseconds 500; Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host 'Himaya has been removed from this computer.' -ForegroundColor Green
"""


def build_windows_uninstaller() -> str:
    return _WINDOWS_UNINSTALLER


# --------------------------------------------------------------------------- #
# Mobile enrollment page
# --------------------------------------------------------------------------- #
_MOBILE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Connect this phone to Himaya</title>
<style nonce="@@NONCE@@">
  :root { --bg:#0c1122; --card:#131a33; --line:#232c4d; --text:#e8ecf8; --muted:#9aa5c7; --brand:#7c94ff; --gold:#e6bf73; }
  @media (prefers-color-scheme: light) { :root { --bg:#f5f6fb; --card:#fff; --line:#dfe3f1; --text:#121a33; --muted:#52608a; --brand:#3f5ae0; --gold:#8a6a1d; } }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:20px; background:var(--bg); color:var(--text);
         font:16px/1.55 "Segoe UI", system-ui, -apple-system, Roboto, sans-serif; }
  main { width:100%; max-width:440px; background:var(--card); border:1px solid var(--line); border-radius:18px; padding:28px 24px; }
  h1 { font:600 1.5rem/1.2 Georgia, "Times New Roman", serif; margin:0 0 6px; }
  p { margin:0 0 14px; color:var(--muted); }
  ol { margin:18px 0; padding-left:1.2rem; } li { margin:10px 0; }
  .hub { display:block; padding:12px 14px; border-radius:10px; border:1px solid var(--line); background:rgba(127,127,160,.08);
         font:600 .95rem ui-monospace, Consolas, monospace; word-break:break-all; color:var(--text); }
  .btn { display:flex; align-items:center; justify-content:center; min-height:48px; margin-top:16px; border-radius:12px; border:0; cursor:pointer;
         background:var(--brand); color:#0c1122; font-weight:700; font-size:1rem; font-family:inherit; text-decoration:none; width:100%; }
  .btn.secondary { background:transparent; color:var(--text); border:1px solid var(--line); }
  .btn:focus-visible { outline:3px solid var(--gold); outline-offset:2px; }
  .note { font-size:.9rem; margin-top:18px; }
</style>
</head>
<body>
<main>
  <h1>Connect this phone to Himaya</h1>
  <p>This phone will be protected by the Himaya hub at:</p>
  <code class="hub" id="hub">@@HUB_TEXT@@</code>
  <ol>
    <li>Install the <strong>Himaya Agent</strong> app on this phone.</li>
    <li>Tap the button below. Himaya will ask you to confirm the hub address.</li>
    <li>Type the 6-digit PIN shown on the <strong>Enroll</strong> page of the parent dashboard.</li>
  </ol>
  <a class="btn" href="@@INTENT_HREF@@">Open the Himaya app</a>
  <button class="btn secondary" type="button" id="copy">Copy hub address</button>
  <p class="note">The PIN is never put in this page or in the link. Only the person holding the parent dashboard can see it.</p>
</main>
<script nonce="@@NONCE@@">
  document.getElementById('copy').addEventListener('click', function () {
    var text = document.getElementById('hub').textContent;
    if (navigator.clipboard) { navigator.clipboard.writeText(text).then(function () { document.getElementById('copy').textContent = 'Copied'; }); }
  });
</script>
</body>
</html>
"""


def build_mobile_enroll_page(hub_url: str, nonce: str) -> str:
    """HTML for ``/enroll/mobile``. ``hub_url`` must already be a safe base URL."""
    if not is_safe_base_url(hub_url):
        raise ValueError("unsafe hub URL")
    encoded = urllib.parse.quote(hub_url, safe="")
    intent = f"intent://enroll?hub={encoded}#Intent;scheme=himaya;package=com.himaya.agent;end"
    return (
        _MOBILE_PAGE.replace("@@NONCE@@", html.escape(nonce, quote=True))
        .replace("@@HUB_TEXT@@", html.escape(hub_url, quote=True))
        .replace("@@INTENT_HREF@@", html.escape(intent, quote=True))
    )
