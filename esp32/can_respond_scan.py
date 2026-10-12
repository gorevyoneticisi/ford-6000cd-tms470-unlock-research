#!/usr/bin/env python3
"""Find the CAN ID / payload that makes the radio bootloader send a frame back.

  python can_respond_scan.py [COMx] [payload_hex]
  python can_respond_scan.py COM10 04         # GET_DEVICE_STATE (default)
  python can_respond_scan.py COM10 3E00        # TesterPresent, etc.

The radio ACKs every frame once awake, so ACK can't tell us its ID. This sends
the given payload to every 11-bit ID (0x000-0x7FF) in NORMAL mode and listens
for any frame that comes back on a DIFFERENT ID - that is a real response from
the radio, and reveals the request->response ID pair. Continuous sending also
keeps the radio's CAN awake.

Prereq: the radio must already be awake/ACKing (run probe_window.py and
power-cycle until you see ACKs, then run this right away).
"""
import sys, time
from slcan_raw import Slcan

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
PAYLOAD = bytes.fromhex(sys.argv[2]) if len(sys.argv) > 2 else bytes([0x04])

def drain(s):
    for _ in range(3):
        s.poll(); time.sleep(0.001)

def main():
    s = Slcan(PORT, bitrate=125000, listen_only=False)
    print(f"scanning 0x000-0x7FF with payload {PAYLOAD.hex().upper()} at 125k\n")

    # warmup: confirm awake and note any UNSOLICITED traffic (keepalive to 0x7FF)
    base = []
    t0 = time.time()
    while time.time() - t0 < 2.0:
        s.send(0x7FF, b"\x00")
        time.sleep(0.04)
        base += s.poll()
    if base:
        print(f"note: {len(base)} unsolicited frame(s) seen during warmup:")
        seen = {}
        for f in base:
            seen.setdefault((f.id, f.ext), f)
        for (i, e), f in seen.items():
            print(f"   {f!r}")
        print()

    hits = {}
    for rid in range(0x000, 0x800):
        drain(s)
        s.send(rid, PAYLOAD)
        end = time.time() + 0.025
        got = []
        while time.time() < end:
            for f in s.poll():
                if f.id != rid:
                    got.append(f)
            time.sleep(0.002)
        if got:
            hits[rid] = got
            for g in got:
                print(f"  RESPONSE: req {rid:03X} -> {g!r}")
        if rid % 0x100 == 0:
            print(f"  ... scanned up to {rid:03X}")

    print("\n=== summary ===")
    if hits:
        for rid, got in sorted(hits.items()):
            ids = sorted({g.id for g in got})
            print(f"  req {rid:03X} -> resp {[f'{i:03X}' for i in ids]}  "
                  f"first={got[0]!r}")
        print("\nFound responder(s). Next: drive that pair with the bootloader "
              "command set over ISO-TP.")
    else:
        print(f"  No responses to payload {PAYLOAD.hex().upper()}. Try another payload "
              "(e.g. 3E00, 1001, 1002, 81, 3E) or confirm the radio is still awake.")
    s.close()

if __name__ == "__main__":
    main()
