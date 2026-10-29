"""tools/wg_setup.py: the key maths must be exactly WireGuard's, and the generated files must be safe."""
from __future__ import annotations

import base64
import importlib.util
import os
import re
import stat
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "wg_setup.py"
spec = importlib.util.spec_from_file_location("wg_setup", TOOL)
wg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wg)  # type: ignore[union-attr]

h = bytes.fromhex


class TestKeyMaths:
    def test_rfc7748_scalar_multiplication_vectors(self):
        assert wg.x25519(h("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"), h("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")).hex() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
        assert wg.x25519(h("4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d"), h("e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a493")).hex() == "95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957"

    def test_rfc7748_diffie_hellman_example(self):
        alice, bob = h("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"), h("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
        alice_pub, bob_pub = wg.x25519(alice, wg.BASE_POINT), wg.x25519(bob, wg.BASE_POINT)
        assert alice_pub.hex() == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
        assert bob_pub.hex() == "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
        assert wg.x25519(alice, bob_pub) == wg.x25519(bob, alice_pub) == h("4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")

    def test_private_keys_are_clamped_like_wg_genkey(self):
        for _ in range(20):
            raw = base64.b64decode(wg.generate_private_key())
            assert len(raw) == 32 and raw[0] & 7 == 0 and raw[31] & 128 == 0 and raw[31] & 64 == 64

    def test_public_key_is_32_bytes_and_stable(self):
        private = wg.generate_private_key()
        assert wg.public_key(private) == wg.public_key(private)
        assert len(base64.b64decode(wg.public_key(private))) == 32
        assert wg.generate_preshared_key() != wg.generate_preshared_key()


class TestSetup:
    def init(self, tmp_path, **kwargs):
        args = dict(endpoint="home.example.com", port=51820, subnet="10.8.0.0/24", force=False)
        args.update(kwargs)
        return wg.cmd_init(tmp_path / "wireguard", args["endpoint"], args["port"], args["subnet"], args["force"])

    def test_init_writes_a_server_config_only_the_owner_can_read(self, tmp_path):
        state = self.init(tmp_path)
        server = (tmp_path / "wireguard" / "server.conf").read_text()
        assert "Address = 10.8.0.1/24" in server and "ListenPort = 51820" in server
        assert f"PrivateKey = {state['server_private_key']}" in server
        if os.name == "posix":
            for name in ("server.conf", "state.json"):
                assert stat.S_IMODE((tmp_path / "wireguard" / name).stat().st_mode) == 0o600

    def test_init_will_not_silently_replace_an_existing_setup(self, tmp_path):
        first = self.init(tmp_path)
        with pytest.raises(wg.SetupError):
            self.init(tmp_path)
        assert self.init(tmp_path, force=True)["server_public_key"] != first["server_public_key"]

    @pytest.mark.parametrize("endpoint", ["home.example.com\nPostUp = rm -rf /", "bad host.com", "a.com:99999", "a.com:abc", "::1", "-bad.com", "a..com", ""])
    def test_endpoint_cannot_inject_config_lines(self, tmp_path, endpoint):
        with pytest.raises(wg.SetupError):
            self.init(tmp_path, endpoint=endpoint)

    @pytest.mark.parametrize("subnet", ["8.8.8.0/24", "10.0.0.0/8", "10.8.0.0/30", "nonsense", "fd00::/64"])
    def test_subnet_must_be_a_sensible_private_range(self, tmp_path, subnet):
        with pytest.raises(wg.SetupError):
            self.init(tmp_path, subnet=subnet)

    def test_endpoint_port_is_filled_in_or_kept(self, tmp_path):
        assert self.init(tmp_path, endpoint="1.2.3.4")["endpoint"] == "1.2.3.4:51820"
        assert self.init(tmp_path, endpoint="home.example.com:443", force=True)["endpoint"] == "home.example.com:443"


class TestDevices:
    @pytest.fixture()
    def folder(self, tmp_path):
        wg.cmd_init(tmp_path / "wireguard", "home.example.com", 51820, "10.8.0.0/24", False)
        return tmp_path / "wireguard"

    def test_each_device_gets_its_own_address_keys_and_file(self, folder):
        first, second = wg.cmd_add(folder, "parent-laptop", False), wg.cmd_add(folder, "dad-phone", False)
        a, b = first.read_text(), second.read_text()
        assert "Address = 10.8.0.2/32" in a and "Address = 10.8.0.3/32" in b
        assert re.search(r"PrivateKey = (\S+)", a).group(1) != re.search(r"PrivateKey = (\S+)", b).group(1)
        assert re.search(r"PresharedKey = (\S+)", a).group(1) != re.search(r"PresharedKey = (\S+)", b).group(1)

    def test_the_device_only_routes_the_hub_through_the_tunnel(self, folder):
        text = wg.cmd_add(folder, "laptop", False).read_text()
        assert "AllowedIPs = 10.8.0.1/32" in text and "0.0.0.0/0" not in text
        assert "Endpoint = home.example.com:51820" in text and "PersistentKeepalive = 25" in text
        assert "DNS =" not in text
        assert "DNS = 10.8.0.1" in wg.cmd_add(folder, "laptop2", True).read_text()

    def test_server_and_device_agree_on_the_keys(self, folder):
        device = wg.cmd_add(folder, "laptop", False).read_text()
        server = (folder / "server.conf").read_text()
        device_private = re.search(r"PrivateKey = (\S+)", device).group(1)
        assert f"PublicKey = {wg.public_key(device_private)}" in server                  # the hub knows the device
        server_private = re.search(r"PrivateKey = (\S+)", server).group(1)
        assert f"PublicKey = {wg.public_key(server_private)}" in device                  # the device knows the hub
        assert re.search(r"PresharedKey = (\S+)", device).group(1) in server
        assert "AllowedIPs = 10.8.0.2/32" in server

    def test_the_device_private_key_is_not_kept_in_the_hubs_state(self, folder):
        device = wg.cmd_add(folder, "laptop", False).read_text()
        private = re.search(r"PrivateKey = (\S+)", device).group(1)
        assert private not in (folder / "state.json").read_text() and private not in (folder / "server.conf").read_text()

    @pytest.mark.parametrize("name", ["../evil", "a/b", "a b", "", ".hidden", "x" * 40, "name\nPostUp=1"])
    def test_device_names_cannot_escape_the_folder(self, folder, name):
        with pytest.raises(wg.SetupError):
            wg.cmd_add(folder, name, False)

    def test_duplicate_names_are_refused(self, folder):
        wg.cmd_add(folder, "laptop", False)
        with pytest.raises(wg.SetupError):
            wg.cmd_add(folder, "laptop", False)

    def test_remove_drops_the_device_from_the_server_and_deletes_its_file(self, folder):
        path = wg.cmd_add(folder, "laptop", False)
        wg.cmd_add(folder, "phone", False)
        wg.cmd_remove(folder, "laptop")
        server = (folder / "server.conf").read_text()
        assert "# laptop" not in server and "# phone" in server and not path.exists()
        assert "Address = 10.8.0.2/32" in wg.cmd_add(folder, "tablet", False).read_text()   # the freed address is reused
        with pytest.raises(wg.SetupError):
            wg.cmd_remove(folder, "ghost")

    def test_a_full_subnet_is_reported(self, tmp_path):
        folder = tmp_path / "wireguard"
        wg.cmd_init(folder, "home.example.com", 51820, "10.8.0.0/29", False)   # 6 usable addresses: the hub and 5 devices
        for i in range(5):
            wg.cmd_add(folder, f"d{i}", False)
        with pytest.raises(wg.SetupError):
            wg.cmd_add(folder, "one-too-many", False)


class TestCommandLine:
    def test_friendly_errors_not_tracebacks(self, tmp_path, capsys):
        assert wg.main(["--dir", str(tmp_path / "none"), "list"]) == 1
        assert "No WireGuard setup" in capsys.readouterr().err

    def test_full_flow(self, tmp_path, capsys):
        d = str(tmp_path / "wireguard")
        assert wg.main(["--dir", d, "init", "--endpoint", "home.example.com"]) == 0
        assert wg.main(["--dir", d, "add", "laptop", "--no-qr"]) == 0
        assert wg.main(["--dir", d, "list"]) == 0
        out = capsys.readouterr().out
        assert "10.8.0.2" in out and "laptop" in out and "http://10.8.0.1:8000" in out
