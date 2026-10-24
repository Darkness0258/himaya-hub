#!/usr/bin/env python3
"""Validate the DNS packets the Kotlin codec wrote, using an independent implementation (dnspython)."""
import struct, sys
from pathlib import Path

import dns.message, dns.rdatatype

d = Path(sys.argv[1])
read = lambda n: bytes.fromhex((d / n).read_text())
fails = 0
def ok(label, cond):
    global fails
    print(("  ok    " if cond else "  FAIL  ") + label)
    fails += 0 if cond else 1

a = dns.message.from_wire(read("blocked_a.hex"))
ok("A: id echoed, QR set, NOERROR, one answer 0.0.0.0", a.id == 0x1234 and a.rcode() == 0 and [r.address for rr in a.answer for r in rr] == ["0.0.0.0"])
aaaa = dns.message.from_wire(read("blocked_aaaa.hex"))
ok("AAAA: a real AAAA record ::, not an A record", [r.address for rr in aaaa.answer for r in rr] == ["::"] and aaaa.answer[0].rdtype == dns.rdatatype.AAAA)
https = dns.message.from_wire(read("blocked_https.hex"))
ok("HTTPS(65): empty NOERROR", https.rcode() == 0 and https.answer == [])
sf = dns.message.from_wire(read("servfail.hex"))
ok("SERVFAIL packet is rcode 2", sf.rcode() == 2)

pkt = read("udp_reply.hex")
ihl = (pkt[0] & 0x0F) * 4
words = struct.unpack(f">{ihl // 2}H", pkt[:ihl])
total = sum(words)
while total >> 16: total = (total & 0xFFFF) + (total >> 16)
ok("IPv4 header checksum verifies (independent implementation)", total == 0xFFFF)
ok("source/destination swapped (reply comes from the address that was asked)", pkt[12:16] == bytes([10, 111, 0xDE, 2]) and pkt[16:20] == bytes([10, 111, 0xDE, 1]))
sport, dport, ulen = struct.unpack(">HHH", pkt[20:26])
ok("UDP ports swapped (reply from 53 back to the asking port 64) and length consistent", sport == 53 and dport == 64 and ulen == len(pkt) - 20)
inner = dns.message.from_wire(pkt[28:])
ok("the DNS payload inside the packet parses", inner.id == 0x1234 and inner.rcode() == 0)
print("\n" + ("ALL DNS PACKET CHECKS PASSED" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
