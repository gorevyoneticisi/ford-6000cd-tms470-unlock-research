#!/usr/bin/env python3
"""Scan for a real diagnostic endpoint on the (now awake) radio.

  python can_uds_scan.py [COMx] [req_hex]
  python can_uds_scan.py COM10 021001     # DiagnosticSessionControl default (def)
  python can_uds_scan.py COM10 023E00     # TesterPresent
  python can_uds_scan.py COM10 0281        # KWP StartCommunication

Sends the request (as one padded CAN frame) to every 11-bit ID and listens for a
genuine reply. The radio's 10 periodic broadcast IDs are filtered out, so a hit
is a frame correlated with our request - a true diagnostic response. UDS/KWP
positive replies echo the service +0x40 (0x10->0x50, 0x3E->0x7E, 0x81->0xC1);
a negative reply is 0x7F <service> <nrc>. Both are flagged.

Continuous sending keeps the radio awake. Prereq: radio already awake (broadcasts
visible). If the warmup shows no broadcasts, re-wake with probe_window.py first.
"""
import sys, time
from slcan_raw import Slcan

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
REQ  = bytes.fromhex(sys.argv[2]) if len(sys.argv) > 2 else bytes([0x02, 0x10, 0x01])

BCAST = {0x1E9, 0x2D5, 0x2D8, 0x2D9, 0x2DA, 0x2DB, 0x2DC, 0x2E3, 0x4D0, 0x50C}

def frame8(payload):
    return bytes(payload) + b"\x00" * (8 - len(payload))

def looks_uds(data):
    if len(data) < 2:
        return ""
    pci = data[0] >> 4
    if pci == 0:         # single frame
        svc = data[1]
    elif pci == 1:       # first frame
        svc = data[2] if len(data) > 2 else 0
    else:
        return ""
    if svc == 0x7F:
        return " NEGATIVE(7F)"
    if svc in (0x50, 0x7E, 0xC1, 0x5A, 0x62, 0x67, 0x71, 0x7A):
        return f" POSITIVE(svc {svc:02X})"
    return ""

def main():
    s = Slcan(PORT, bitrate=125000, listen_only=False)
    print(f"UDS/KWP scan 0x000-0x7FF, request {REQ.hex().upper()} at 125k")
    print(f"(filtering broadcast IDs {sorted(hex(b) for b in BCAST)})\n")

    # warmup / awake check
    t0 = time.time(); base = []
    while time.time() - t0 < 1.5:
        s.send(0x7FF, b"\x00"); time.sleep(0.04); base += s.poll()
    nb = [f for f in base if f.id not in BCAST]
    print(f"warmup: {len(base)} frames ({len(nb)} non-broadcast). "
          f"{'awake' if base else 'NO TRAFFIC - radio may be asleep'}\n")

    data = frame8(REQ)
    hits = {}
    for rid in range(0x000, 0x800):
        for _ in range(2):
            s.poll()
        s.send(rid, data)
        end = time.time() + 0.03
        got = []
        while time.time() < end:
            for f in s.poll():
                if f.id != rid and f.id not in BCAST:
                    got.append(f)
            time.sleep(0.002)
        if got:
            hits.setdefault(rid, [])
            for g in got:
                tag = looks_uds(g.data)
                hits[rid].append((g, tag))
                print(f"  HIT req {rid:03X} -> {g!r}{tag}")
        if rid % 0x100 == 0:
            print(f"  ... {rid:03X}")

    print("\n=== summary ===")
    if hits:
        for rid in sorted(hits):
            for g, tag in hits[rid]:
                print(f"  req {rid:03X} -> resp {g.id:03X}  {g.data.hex(' ').upper()}{tag}")
    else:
        print("  No non-broadcast responses. Try another request (023E00, 0281, "
              "021003, 021081) or the radio uses a different diagnostic scheme.")
    s.close()

if __name__ == "__main__":
    main()
