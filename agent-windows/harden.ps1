<#
.SYNOPSIS
  Optional hardening of Himaya on a CHILD's Windows PC. Run as Administrator, by the parent.

.DESCRIPTION
  The normal Himaya installer lives entirely inside the child's own account, so the child can delete it.
  This script moves the agent to C:\Program Files\Himaya, where only an Administrator can change it,
  and starts it with a Task Scheduler job that brings it back within 5 minutes if it is closed.

  What it does NOT do:
    * It does not hide Himaya. The tray icon and the notices stay.
    * It does not make Himaya unstoppable. A Standard user can still end the running program;
      it comes back within 5 minutes and the hub tells you it went offline.
    * It cannot protect against a child who is an Administrator. Use a Standard account.

  Read docs\TAMPER-RESISTANCE.md first. Tell the child before you run this.

  STATUS: written but not yet run on a real Windows PC. Try it with -DryRun first, then on a spare PC.

.PARAMETER ChildUser
  The child's Windows account name (see Settings > Accounts). The normal Himaya installer must already
  have been run while signed in as that account.

.PARAMETER Remove
  Undo this hardening and remove Himaya from the PC completely.

.PARAMETER DryRun
  Show what would be done. Changes nothing.

.PARAMETER Yes
  Do not ask for confirmation (you have told the child).

.PARAMETER Force
  Allow it for an Administrator account. Pointless, because an Administrator can undo it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\harden.ps1 -ChildUser sarah -DryRun

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\harden.ps1 -ChildUser sarah -Remove
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ChildUser,
    [switch]$Remove,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$TaskName  = 'Himaya Agent'
$TaskPath  = '\Himaya\'
$Target    = Join-Path $env:ProgramFiles 'Himaya'
$AgentFile = 'himaya_windows_agent.py'
$Blackhole = '127.0.0.1:9'   # the "pause internet" proxy the agent sets (must match the agent)

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { Write-Host ''; Write-Host ('==> ' + $Text) -ForegroundColor Cyan }

# Every change goes through here, so -DryRun can show it without doing it.
function Invoke-Change([string]$What, [scriptblock]$Block) {
    if ($DryRun) { Say ('    [dry run] ' + $What) 'Yellow'; return }
    Say ('    ' + $What)
    & $Block
}

function Confirm-Or-Stop([string]$Question) {
    if ($Yes -or $DryRun) { return }
    Say ''
    Say $Question 'Yellow'
    $answer = (Read-Host '  Type YES to continue').Trim().ToLower()
    if ($answer -ne 'yes') { throw 'Cancelled. Nothing was changed.' }
}

function Stop-Agent {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like ('*' + $AgentFile + '*') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# Tell the parent's hub what happened, using the device's own key from its config file.
function Send-HubNotice([string]$ConfigPath, [string]$Type, [hashtable]$Data) {
    if ($DryRun) { Say ('    [dry run] would tell the hub: ' + $Type) 'Yellow'; return }
    try {
        $cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
        $body = @{ type = $Type; data = $Data } | ConvertTo-Json -Compress -Depth 4
        $uri = ([string]$cfg.hub_url).TrimEnd('/') + '/agents/' + $cfg.device_id + '/event'
        Invoke-RestMethod -Uri $uri -Method Post -Headers @{ 'X-API-Key' = $cfg.agent_key } `
            -ContentType 'application/json' -Body $body -TimeoutSec 6 | Out-Null
        Say '    told the hub'
    } catch {
        Say '    could not reach the hub to tell it (continuing)' 'Yellow'
    }
}

try {
    # ---- who is the child? -------------------------------------------------------------- #
    $user = Get-LocalUser -Name $ChildUser -ErrorAction SilentlyContinue
    if (-not $user) {
        throw ("There is no local Windows account named '" + $ChildUser + "'. Check the name under Settings > Accounts.")
    }
    $sid = $user.SID.Value
    $profilePath = (Get-CimInstance Win32_UserProfile -Filter ("SID='" + $sid + "'") -ErrorAction SilentlyContinue).LocalPath
    if (-not $profilePath -or -not (Test-Path $profilePath)) {
        throw ("'" + $ChildUser + "' has never signed in on this PC. Sign in as that account once and run the normal Himaya installer.")
    }
    $account = $env:COMPUTERNAME + '\' + $user.Name

    $isAdmin = $false
    try {
        $isAdmin = [bool](Get-LocalGroupMember -Group 'Administrators' -ErrorAction Stop | Where-Object { $_.SID.Value -eq $sid })
    } catch { }
    if ($isAdmin -and -not $Force) {
        throw ("'" + $ChildUser + "' is an Administrator, and an Administrator can undo any protection. " +
               'Make it a Standard account first (Settings > Accounts > Family & other users > Change account type), then run this again.')
    }

    $src = Join-Path $profilePath 'AppData\Local\HimayaAgent'
    $startupLink = Join-Path $profilePath 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Himaya Agent.lnk'

    # ---- remove ------------------------------------------------------------------------- #
    if ($Remove) {
        Confirm-Or-Stop ('This removes Himaya from this PC completely (account: ' + $ChildUser + ').')
        Step 'Telling the hub'
        $cfgPath = Join-Path $Target 'agent_config.json'
        if (Test-Path $cfgPath) { Send-HubNotice $cfgPath 'agent_stopped' @{ reason = 'uninstalled'; by = $env:USERNAME } }

        Step 'Removing the scheduled job and the program'
        Invoke-Change 'removing the Task Scheduler job' {
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false -ErrorAction SilentlyContinue
        }
        Invoke-Change 'stopping the agent' { Stop-Agent }
        Invoke-Change ('deleting ' + $Target) {
            Start-Sleep -Milliseconds 500
            Remove-Item -Path $Target -Recurse -Force -ErrorAction SilentlyContinue
        }

        Step 'Undoing what the agent may have left behind'
        Invoke-Change 'restoring internet settings for the child (only if the child is signed in)' {
            try {
                $key = 'Registry::HKEY_USERS\' + $sid + '\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
                if (Test-Path $key) {
                    $p = Get-ItemProperty -Path $key -ErrorAction Stop
                    if ($p.ProxyServer -eq $Blackhole) {
                        Set-ItemProperty -Path $key -Name ProxyEnable -Value 0
                        Remove-ItemProperty -Path $key -Name ProxyServer -ErrorAction SilentlyContinue
                    }
                }
            } catch { }
        }
        Invoke-Change 'removing the website block list from the hosts file' {
            try {
                $hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
                $text = Get-Content -Raw -Path $hosts
                if ($text -match '# HIMAYA BLOCKLIST START') {
                    $clean = [regex]::Replace($text, '(?s)\r?\n?# HIMAYA BLOCKLIST START.*?# HIMAYA BLOCKLIST END\r?\n?', "`r`n")
                    Set-Content -Path $hosts -Value $clean -Encoding ASCII
                }
            } catch { }
        }
        Say ''
        if ($DryRun) { Say 'Dry run finished. Nothing was changed.' 'Yellow' } else { Say 'Himaya has been removed from this PC.' 'Green' }
        return
    }

    # ---- harden ------------------------------------------------------------------------- #
    if (-not (Test-Path (Join-Path $src $AgentFile)) -or -not (Test-Path (Join-Path $src 'agent_config.json'))) {
        throw ("Himaya is not installed for '" + $ChildUser + "' yet. Sign in as that account, run the Himaya installer from the dashboard, then run this script again.")
    }

    # Which Python does the agent use? The installer's Startup shortcut points at it.
    $pyw = $null
    if (Test-Path $startupLink) {
        try { $pyw = (New-Object -ComObject WScript.Shell).CreateShortcut($startupLink).TargetPath } catch { }
    }
    if (-not $pyw -or -not (Test-Path $pyw)) {
        throw 'Could not find the Python program the agent uses (the Startup shortcut is missing). Run the normal Himaya installer as the child again, then retry.'
    }
    if ($pyw.StartsWith($profilePath, [StringComparison]::OrdinalIgnoreCase)) {
        Say ('Note: Python is installed inside ' + $ChildUser + "'s own folder, so the child could replace it.") 'Yellow'
        Say '      For a stronger setup install it for all users: winget install -e --id Python.Python.3.12 --scope machine' 'Yellow'
    }

    Say ''
    Say 'Himaya hardening' 'Cyan'
    Say ('  Child account : ' + $account)
    Say ('  Agent moves to: ' + $Target + '  (only Administrators can change it)')
    Say '  It starts when the child signs in, and comes back within 5 minutes if closed.'
    Say '  The tray icon stays visible. Tell the child before you do this.'
    Confirm-Or-Stop 'Continue?'

    $agentPath = Join-Path $Target $AgentFile

    Step 'Pausing the old copy'
    Invoke-Change 'stopping the running agent' { Stop-Agent }

    Step 'Copying the agent to a protected folder'
    Invoke-Change ('creating ' + $Target) { New-Item -ItemType Directory -Force -Path $Target | Out-Null }
    Invoke-Change 'copying the agent and its settings' {
        Copy-Item -Path (Join-Path $src $AgentFile) -Destination $Target -Force
        Copy-Item -Path (Join-Path $src 'agent_config.json') -Destination $Target -Force
    }
    Invoke-Change 'locking the folder: Administrators and SYSTEM full control, the child read and run only' {
        & icacls.exe $Target /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' ('*' + $sid + ':(OI)(CI)RX') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not set the folder permissions.' }
    }

    Step 'Registering the Task Scheduler job'
    Invoke-Change ("creating the job '" + $TaskPath + $TaskName + "' for " + $account) {
        $action = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $agentPath + '"') -WorkingDirectory $Target
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
        # Also try again every 5 minutes. While the agent runs, extra starts are ignored (see -MultipleInstances).
        $again = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
        $trigger.Repetition = $again.Repetition
        $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action -Trigger $trigger -Principal $principal `
            -Settings $settings -Description 'Himaya family safety agent (visible in the system tray)' -Force | Out-Null
    }

    Step 'Replacing the old per-user install'
    Invoke-Change 'removing the child-writable Startup shortcut and folder' {
        if (Test-Path $startupLink) { Remove-Item -Path $startupLink -Force -ErrorAction SilentlyContinue }
        if (Test-Path $src) { Remove-Item -Path $src -Recurse -Force -ErrorAction SilentlyContinue }
    }

    Step 'Starting it'
    Invoke-Change 'starting the job now (it runs in the child session if they are signed in)' {
        try { Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath }
        catch { Say '    the child is not signed in; it will start at their next sign-in' 'Yellow' }
    }
    Send-HubNotice (Join-Path $Target 'agent_config.json') 'enforcement_notice' @{
        kind = 'hardened'
        message = 'An administrator hardened Himaya on this PC. It now restarts itself within 5 minutes if it is closed.'
    }

    Say ''
    if ($DryRun) {
        Say 'Dry run finished. Nothing was changed. Run again without -DryRun to apply it.' 'Yellow'
        return
    }
    Say 'Done.' 'Green'
    Say '  * The child can no longer delete the agent or its Startup entry.'
    Say '  * If the child ends the program, it returns within 5 minutes and the hub shows the PC went offline.'
    Say ('  * To undo everything: .\harden.ps1 -ChildUser ' + $ChildUser + ' -Remove')
    Say '  * Website blocking: a Standard account cannot edit the hosts file. For strong blocking, point the DNS of this PC at the hub (docs\DEPLOY.md).'
    Say ''
} catch {
    Write-Host ''
    Write-Host ('  Himaya hardening stopped: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ''
    exit 1
}
