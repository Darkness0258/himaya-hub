#!/usr/bin/env python3
"""Fail if a real-looking secret, or a file that must never be committed, is in the project.

    python tools/check_secrets.py              # check this project
    python tools/check_secrets.py --root ../x  # check another folder

Run it before you push. The hub's test suite runs it too (hub/tests/test_no_secrets.py), so a leak fails
the tests instead of reaching GitHub.

What it looks for:
  * Himaya keys (hma_... admin keys, hag_... device keys) that are not obviously fake,
  * database passwords inside postgres:// addresses, JWTs, private keys, and common cloud tokens,
  * files that hold secrets or private data: .env, *.db, admin_key.txt, local.properties, signing keys,
    WireGuard keys, AdGuard runtime data, and the hub's data folder.

To write an example key in a test or in docs, make it obviously fake: for example hma_EXAMPLE-not-a-real-key.
If a real secret ever reaches GitHub, replacing it is not enough: rotate it, because it stays in the history.

It prints where the problem is and the first few characters, never the whole secret.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", ".gradle", ".idea", "dist", "build"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".jar", ".zip", ".gz", ".apk", ".aab", ".so", ".pdf"}
MAX_BYTES = 2_000_000

FORBIDDEN_FILES = [
    (re.compile(r"(^|/)\.env$"), "an environment file (commit .env.example instead)"),
    (re.compile(r"\.(db|sqlite3?|db-wal|db-shm)$", re.I), "a database file"),
    (re.compile(r"(^|/)admin_key\.txt$"), "the hub's admin key file"),
    (re.compile(r"(^|/)local\.properties$"), "an Android local.properties file"),
    (re.compile(r"\.(jks|keystore|pem|p12|pfx)$", re.I), "a signing key or certificate"),
    (re.compile(r"^wireguard/"), "WireGuard keys"),
    (re.compile(r"^adguard/(work|conf)/"), "AdGuard runtime data"),
    (re.compile(r"^hub/data/(?!(?:.*/)?\.gitkeep$)"), "the hub's runtime data"),
]

KEY_RE = re.compile(r"\b(?:hma|hag)_[A-Za-z0-9_-]{24,}")
PG_RE = re.compile(r"postgres(?:ql)?://([^:\s/@'\"<>]+):([^@\s'\"<>]+)@")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
SUPABASE_RE = re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]{10,}")
TOKEN_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{36}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bsk-[A-Za-z0-9]{32,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}")

# Words that mark a value as an obvious placeholder.
FAKE_WORDS = ("example", "fake", "dummy", "placeholder", "notreal", "not-a-real", "not_a_real", "redacted", "xxxx", "0000", "test", "demo", "your-", "your_")
FAKE_PASSWORDS = {"password", "pass", "passwd", "pwd", "secret", "changeme", "postgres", "user", "p", "yourpassword"}


class Finding(NamedTuple):
    path: str
    line: int
    kind: str
    sample: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}  {self.kind}  ({self.sample})"


def mask(text: str) -> str:
    return f"{text[:8]}... {len(text)} characters"


def looks_fake(value: str) -> bool:
    lowered = value.lower()
    return any(word in lowered for word in FAKE_WORDS)


def candidate_files(root: Path) -> List[str]:
    """Files git knows about (tracked, or untracked but not ignored). Without git: every file on disk."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-c", "-o", "--exclude-standard", "-z"], capture_output=True, check=True, timeout=60).stdout
        return sorted(p for p in out.decode("utf-8", "replace").split("\0") if p)
    except (OSError, subprocess.SubprocessError):
        found = []
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if path.is_file() and not any(part in SKIP_DIRS for part in relative.parts):
                found.append(relative.as_posix())
        return sorted(found)


def scan(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    for relative in candidate_files(root):
        path = root / relative
        if not path.is_file() or any(part in SKIP_DIRS for part in Path(relative).parts):
            continue
        for pattern, why in FORBIDDEN_FILES:
            if pattern.search(relative):
                findings.append(Finding(relative, 0, f"must not be committed: {why}", Path(relative).name))
        if path.suffix.lower() in BINARY_SUFFIXES or path.stat().st_size > MAX_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in KEY_RE.finditer(line):
                if not looks_fake(match.group(0)):
                    findings.append(Finding(relative, number, "a Himaya key that does not look fake", mask(match.group(0))))
            for match in PG_RE.finditer(line):
                password = match.group(2)
                if password.lower() not in FAKE_PASSWORDS and not looks_fake(password) and password[0] not in "[<${(":
                    findings.append(Finding(relative, number, "a database password inside a postgres:// address", mask(match.group(0))))
            for kind, pattern in (("a JWT", JWT_RE), ("a private key", PRIVATE_KEY_RE), ("a Supabase key", SUPABASE_RE), ("a cloud or API token", TOKEN_RE)):
                for match in pattern.finditer(line):
                    findings.append(Finding(relative, number, kind, mask(match.group(0))))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if a secret or a must-not-commit file is in the project.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="folder to check (default: this project)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2
    findings = scan(root)
    if not findings:
        print("No secrets or forbidden files found.")
        return 0
    print(f"Found {len(findings)} problem(s):\n")
    for finding in findings:
        print(f"  {finding}")
    print("\nFix: use an obviously fake value (for example hma_EXAMPLE-not-a-real-key), and remove forbidden files from git.")
    print("If a real secret was already pushed, rotate it: replacing it in a new commit does not remove it from history.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
