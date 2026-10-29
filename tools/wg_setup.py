#!/usr/bin/env python3
"""Create WireGuard configs so your own devices can reach the Himaya hub away from home.

Pure Python: no `wg` program and no extra packages needed (the key maths is X25519, RFC 7748).

    python tools/wg_setup.py init --endpoint home.example.com        # once: makes the server config
    python tools/wg_setup.py add parent-laptop                        # one config per device
    python tools/wg_setup.py list
    python tools/wg_setup.py remove parent-laptop

Everything goes into ./wireguard (change with --dir). That folder holds SECRET keys: it is in .gitignore,
keep it that way and do not share it. Each peer file contains that device's private key, so import it
into the WireGuard app and then delete the file.

Peers can reach ONLY the hub (10.8.0.1 by default). Their other traffic does not go through your home.
Read docs/REMOTE-ACCESS.md first. In particular: an Android phone can run only one VPN at a time, and
Himaya's own website filter is one. Use HTTPS for phones; use this for PCs, laptops and the parent's devices.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# X25519 (RFC 7748, section 5). Slow (a few ms) but only used to make a key pair.
# --------------------------------------------------------------------------- #
_P = 2**255 - 19
_A24 = 121665
BASE_POINT = (9).to_bytes(32, "little")


def clamp_private_key(raw: bytes) -> bytes:
    if len(raw) != 32:
        raise ValueError("a private key is 32 bytes")
    key = bytearray(raw)
    key[0] &= 248
    key[31] &= 127
    key[31] |= 64
    return bytes(key)


def x25519(scalar: bytes, u_bytes: bytes) -> bytes:
    k = int.from_bytes(clamp_private_key(scalar), "little")
    u = int.from_bytes(u_bytes, "little") & ((1 << 255) - 1)
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    for t in reversed(range(255)):
        bit = (k >> t) & 1
        swap ^= bit
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = bit
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = pow(da + cb, 2, _P)
        z3 = x1 * pow(da - cb, 2, _P) % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def generate_private_key() -> str:
    """Same as `wg genkey`."""
    return base64.b64encode(clamp_private_key(os.urandom(32))).decode("ascii")


def public_key(private_b64: str) -> str:
    """Same as `wg pubkey`."""
    return base64.b64encode(x25519(base64.b64decode(private_b64), BASE_POINT)).decode("ascii")


def generate_preshared_key() -> str:
    """Same as `wg genpsk`."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


# --------------------------------------------------------------------------- #
# State and config files
# --------------------------------------------------------------------------- #
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
STATE_FILE = "state.json"
SERVER_FILE = "server.conf"


class SetupError(Exception):
    """A problem the person can fix; shown without a traceback."""


def check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise SetupError("Use 1 to 32 letters, numbers, dash or underscore for a device name (for example: parent-laptop).")
    return name


def check_endpoint(endpoint: str, port: int) -> str:
    """`host` or `host:port` -> `host:port`. Rejects anything that could inject extra config lines."""
    text = (endpoint or "").strip()
    host, _, given = text.partition(":") if text.count(":") == 1 else (text, "", "")
    if text.count(":") > 1:
        raise SetupError("IPv6 endpoints are not supported here. Use a host name or an IPv4 address.")
    try:
        use_port = int(given) if given else port
    except ValueError:
        raise SetupError("The port after the colon must be a number.") from None
    if not 1 <= use_port <= 65535:
        raise SetupError("The port must be between 1 and 65535.")
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        if not HOST_RE.match(host) or len(host) > 253:
            raise SetupError("The endpoint must be your home's public address: a name like home.duckdns.org or an IPv4 address.") from None
    return f"{host}:{use_port}"


def write_secret(path: Path, text: str) -> None:
    """Write a file only the owner can read (best effort on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_state(folder: Path) -> Dict[str, Any]:
    path = folder / STATE_FILE
    if not path.exists():
        raise SetupError(f"No WireGuard setup in {folder}. Run: python tools/wg_setup.py init --endpoint your-home-address")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(folder: Path, state: Dict[str, Any]) -> None:
    write_secret(folder / STATE_FILE, json.dumps(state, indent=2) + "\n")
    write_secret(folder / SERVER_FILE, render_server(state))


def render_server(state: Dict[str, Any]) -> str:
    network = ipaddress.ip_network(state["subnet"])
    lines = [
        "# Himaya hub: WireGuard server. Generated by tools/wg_setup.py. Contains a SECRET key.",
        "[Interface]",
        f"Address = {state['server_address']}/{network.prefixlen}",
        f"ListenPort = {state['port']}",
        f"PrivateKey = {state['server_private_key']}",
    ]
    for peer in state["peers"]:
        lines += ["", f"# {peer['name']}", "[Peer]", f"PublicKey = {peer['public_key']}", f"PresharedKey = {peer['preshared_key']}", f"AllowedIPs = {peer['address']}/32"]
    return "\n".join(lines) + "\n"


def render_peer(state: Dict[str, Any], peer: Dict[str, Any], private_key: str, with_dns: bool) -> str:
    lines = [
        f"# Himaya: {peer['name']}. Contains this device's SECRET key: import it, then delete this file.",
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {peer['address']}/32",
    ]
    if with_dns:
        lines.append(f"DNS = {state['server_address']}")
    lines += [
        "",
        "[Peer]",
        f"PublicKey = {state['server_public_key']}",
        f"PresharedKey = {peer['preshared_key']}",
        f"Endpoint = {state['endpoint']}",
        f"AllowedIPs = {state['server_address']}/32",   # only the hub goes through the tunnel
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(folder: Path, endpoint: str, port: int, subnet: str, force: bool) -> Dict[str, Any]:
    if (folder / STATE_FILE).exists() and not force:
        raise SetupError(f"{folder} already has a setup. Use `add` for new devices, or --force to start over (this invalidates every existing device config).")
    try:
        network = ipaddress.ip_network(subnet, strict=True)
    except ValueError:
        raise SetupError("The subnet must look like 10.8.0.0/24.") from None
    if not isinstance(network, ipaddress.IPv4Network) or not network.is_private or not 16 <= network.prefixlen <= 29:
        raise SetupError("Use a private IPv4 subnet between /16 and /29, for example 10.8.0.0/24.")
    if not 1 <= port <= 65535:
        raise SetupError("The port must be between 1 and 65535.")
    private = generate_private_key()
    state = {
        "version": 1,
        "endpoint": check_endpoint(endpoint, port),
        "port": port,
        "subnet": str(network),
        "server_address": str(next(network.hosts())),
        "server_private_key": private,
        "server_public_key": public_key(private),
        "peers": [],
    }
    save_state(folder, state)
    return state


def next_address(state: Dict[str, Any]) -> str:
    network = ipaddress.ip_network(state["subnet"])
    used = {state["server_address"]} | {p["address"] for p in state["peers"]}
    for host in network.hosts():
        if str(host) not in used:
            return str(host)
    raise SetupError("The subnet is full. Remove a device, or start over with a bigger subnet.")


def cmd_add(folder: Path, name: str, with_dns: bool) -> Path:
    check_name(name)
    state = load_state(folder)
    if any(p["name"] == name for p in state["peers"]):
        raise SetupError(f"There is already a device called '{name}'. Pick another name, or remove it first.")
    private = generate_private_key()
    peer = {"name": name, "address": next_address(state), "public_key": public_key(private), "preshared_key": generate_preshared_key()}
    state["peers"].append(peer)
    save_state(folder, state)
    path = folder / f"{name}.conf"
    write_secret(path, render_peer(state, peer, private, with_dns))
    return path


def cmd_remove(folder: Path, name: str) -> None:
    check_name(name)
    state = load_state(folder)
    kept = [p for p in state["peers"] if p["name"] != name]
    if len(kept) == len(state["peers"]):
        raise SetupError(f"No device called '{name}'. See: python tools/wg_setup.py list")
    state["peers"] = kept
    save_state(folder, state)
    leftover = folder / f"{name}.conf"
    if leftover.exists():
        leftover.unlink()


def print_qr(text: str) -> None:
    try:
        import qrcode  # already a dependency of the hub
    except ImportError:
        return
    code = qrcode.QRCode(border=1)
    code.add_data(text)
    code.make(fit=True)
    print("\nScan this in the WireGuard app (Add tunnel > Scan from QR code):\n")
    code.print_ascii(invert=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="WireGuard setup for the Himaya hub")
    parser.add_argument("--dir", default="wireguard", help="where the files go (default: ./wireguard)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="create the server config")
    p_init.add_argument("--endpoint", required=True, help="your home's public address, like home.duckdns.org (or host:port)")
    p_init.add_argument("--port", type=int, default=51820, help="UDP port to open on your router (default 51820)")
    p_init.add_argument("--subnet", default="10.8.0.0/24")
    p_init.add_argument("--force", action="store_true")
    p_add = sub.add_parser("add", help="add a device and write its config")
    p_add.add_argument("name")
    p_add.add_argument("--dns", action="store_true", help="also send the device's DNS to the hub (needs HIMAYA_DNS_PORT=53)")
    p_add.add_argument("--no-qr", action="store_true")
    p_rm = sub.add_parser("remove", help="remove a device")
    p_rm.add_argument("name")
    sub.add_parser("list", help="show the devices")
    args = parser.parse_args(argv)
    folder = Path(args.dir)

    try:
        if args.command == "init":
            state = cmd_init(folder, args.endpoint, args.port, args.subnet, args.force)
            print(f"Created {folder / SERVER_FILE}")
            print(f"  Hub address inside the tunnel: http://{state['server_address']}:8000")
            print(f"  Open UDP port {state['port']} on your router and forward it to the hub computer.")
            print(f"  Start it: Linux `sudo wg-quick up {(folder / SERVER_FILE).resolve()}`; Windows: import it in the WireGuard app.")
            print("  Next: python tools/wg_setup.py add <device-name>")
        elif args.command == "add":
            path = cmd_add(folder, args.name, args.dns)
            print(f"Created {path}  (it holds a SECRET key: import it, then delete it)")
            print("The hub's server.conf was updated: reload it (`sudo wg syncconf` / restart the tunnel).")
            if not args.no_qr:
                print_qr(path.read_text(encoding="utf-8"))
        elif args.command == "remove":
            cmd_remove(folder, args.name)
            print(f"Removed '{args.name}'. Reload the hub's tunnel so the change takes effect.")
        elif args.command == "list":
            state = load_state(folder)
            print(f"Hub {state['server_address']}  endpoint {state['endpoint']}  subnet {state['subnet']}")
            for peer in state["peers"]:
                print(f"  {peer['address']:<14} {peer['name']}")
            if not state["peers"]:
                print("  (no devices yet)")
    except SetupError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
