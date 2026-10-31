"""Every PowerShell script Himaya ships must at least parse, in every PowerShell on this computer.

A syntax error in an installer only shows up on someone's PC, so catch it here. This covers harden.ps1 and the
installer and uninstaller the hub generates. The CI runners have PowerShell 7 (`pwsh`), and the Windows one also has
Windows PowerShell 5.1 (`powershell`), which is the one a real family PC runs. Skipped where there is no PowerShell.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import templates

ROOT = Path(__file__).resolve().parents[2]
SHELLS = [name for name in ("pwsh", "powershell") if shutil.which(name)]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache"}

PARSER = """
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
$bad = 0
foreach ($p in $Paths) {
    $errors = $null; $tokens = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$tokens, [ref]$errors)
    if ($errors.Count -eq 0) { "OK|$p" }
    else { $bad++; foreach ($e in $errors) { "ERR|$p|line $($e.Extent.StartLineNumber)|$($e.Message)" } }
}
exit $bad
"""


def shipped_scripts() -> list:
    return sorted(p for p in ROOT.rglob("*.ps1") if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts))


@pytest.mark.skipif(not SHELLS, reason="no PowerShell installed")
@pytest.mark.parametrize("shell", SHELLS)
def test_every_shipped_script_parses(shell, tmp_path):
    files = shipped_scripts()
    assert any(p.name == "harden.ps1" for p in files), "harden.ps1 should be among the scripts checked"
    # The hub builds these two on demand. A BOM makes Windows PowerShell 5.1 read them as UTF-8.
    for name, text in (("generated-installer.ps1", templates.build_windows_installer(["http://192.168.1.20:8000"])),
                       ("generated-uninstaller.ps1", templates.build_windows_uninstaller())):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8-sig")
        files.append(path)
    parser = tmp_path / "parse.ps1"
    parser.write_text(PARSER, encoding="utf-8-sig")
    command = [shutil.which(shell), "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        command += ["-ExecutionPolicy", "Bypass"]
    result = subprocess.run(command + ["-File", str(parser)] + [str(p) for p in files], capture_output=True, text=True, timeout=180)
    lines = result.stdout.splitlines()
    problems = [line for line in lines if line.startswith("ERR|")]
    assert not problems, f"{shell} could not parse:\n" + "\n".join(problems)
    assert sum(line.startswith("OK|") for line in lines) == len(files), f"{shell} did not check every file:\n{result.stdout}\n{result.stderr}"
