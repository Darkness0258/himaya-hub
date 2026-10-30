"""No real secrets or must-not-commit files in the project, and the scanner that checks it.

The fake secrets below are assembled at run time, so this file never contains a real-looking secret itself.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "tools" / "check_secrets.py")
checker = importlib.util.module_from_spec(spec)
sys.modules["check_secrets"] = checker
spec.loader.exec_module(checker)  # type: ignore[union-attr]

RANDOM_PART = "q7Gd2Lm9XvB4tR8sYc1Wn6PzKa3HjUe5"
ADMIN = "hma" + "_" + RANDOM_PART
DEVICE = "hag" + "_" + RANDOM_PART
JWT = "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ" + "." + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
PRIVATE = "-----BEGIN " + "PRIVATE KEY-----"
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
PG_REAL = "postgres" + "ql://app:" + "Sup3rS3cretPw" + "@db.internal:5432/himaya"


def tree(tmp_path, files):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return tmp_path


def kinds(tmp_path):
    return [(f.path, f.kind) for f in checker.scan(tmp_path)]


def test_the_project_itself_has_no_secrets():
    findings = checker.scan(ROOT)
    assert not findings, "Secrets or forbidden files found:\n" + "\n".join(f"  {f}" for f in findings)


class TestKeys:
    @pytest.mark.parametrize("key", [ADMIN, DEVICE])
    def test_real_looking_keys_are_caught(self, tmp_path, key):
        found = kinds(tree(tmp_path, {"a/Test.kt": f'val k = "{key}"\n'}))
        assert found == [("a/Test.kt", "a Himaya key that does not look fake")]

    @pytest.mark.parametrize("text", [
        "hma_EXAMPLE-not-a-real-key-000000000000000000",
        "hag_fake_device_key_for_tests_only_00000",
        "Paste hma_... here",
        "hag_abc123",
        "the prefix hma_ is for admin keys",
    ])
    def test_obvious_placeholders_and_short_examples_are_fine(self, tmp_path, text):
        assert kinds(tree(tmp_path, {"docs/x.md": text + "\n"})) == []

    def test_the_line_number_is_reported(self, tmp_path):
        found = checker.scan(tree(tmp_path, {"x.py": f"one\ntwo\nkey = '{ADMIN}'\n"}))
        assert [(f.path, f.line) for f in found] == [("x.py", 3)]


class TestOtherSecrets:
    def test_database_passwords(self, tmp_path):
        assert [k for _, k in kinds(tree(tmp_path, {"x.env": PG_REAL + "\n"}))] == ["a database password inside a postgres:// address"]

    @pytest.mark.parametrize("address", [
        "postgresql://user:password@host:5432/postgres",
        "postgresql://u:${DB_PASSWORD}@h/db",
        "postgresql://u:[YOUR-PASSWORD]@h/db",
        "postgresql://u:<password>@h/db",
        "postgresql://localhost/db",
    ])
    def test_placeholder_database_addresses_are_fine(self, tmp_path, address):
        assert kinds(tree(tmp_path, {".env.example": f"#DATABASE_URL={address}\n"})) == []

    @pytest.mark.parametrize("secret,expected", [(JWT, "a JWT"), (PRIVATE, "a private key"), (AWS, "a cloud or API token")])
    def test_other_secret_shapes(self, tmp_path, secret, expected):
        assert [k for _, k in kinds(tree(tmp_path, {"cfg.txt": f"x = {secret}\n"}))] == [expected]


class TestForbiddenFiles:
    @pytest.mark.parametrize("name", [
        ".env", "hub/.env", "hub/himaya.db", "adguard/work/data/sessions.db", "hub/data/admin_key.txt",
        "himaya-mobile/local.properties", "app/release.keystore", "certs/server.pem", "wireguard/server.conf",
        "adguard/conf/AdGuardHome.yaml", "hub/data/snapshots/kid/1.jpg",
    ])
    def test_files_that_must_not_be_committed(self, tmp_path, name):
        assert any("must not be committed" in kind for _, kind in kinds(tree(tmp_path, {name: "x"})))

    @pytest.mark.parametrize("name", [".env.example", "hub/.env.example", "hub/data/.gitkeep", "hub/data/snapshots/.gitkeep", "docs/a.md"])
    def test_files_that_are_fine(self, tmp_path, name):
        assert kinds(tree(tmp_path, {name: "x"})) == []


class TestScope:
    def test_vendor_folders_and_binaries_are_skipped(self, tmp_path):
        files = {"node_modules/lib/x.js": f"k='{ADMIN}'", "dashboard/node_modules/y.js": f"k='{ADMIN}'", "docs/pic.png": ADMIN.encode()}
        assert kinds(tree(tmp_path, files)) == []

    def test_the_output_never_shows_the_whole_secret(self, tmp_path, capsys):
        tree(tmp_path, {"x.py": f"k='{ADMIN}'\n"})
        assert checker.main(["--root", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert ADMIN not in out and RANDOM_PART not in out and "hma_q7Gd..." in out and "rotate" in out

    def test_exit_codes(self, tmp_path, capsys):
        assert checker.main(["--root", str(tree(tmp_path, {"ok.txt": "fine"}))]) == 0
        assert checker.main(["--root", str(tmp_path / "missing")]) == 2
