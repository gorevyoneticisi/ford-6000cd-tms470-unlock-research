#!/usr/bin/env python3
"""Read-only UDS exploration on 0x727/0x72F: security seed + memory read.

Nothing here writes. It requests security 'seeds' (which are read-only; the ECU
only reveals a challenge) and tries ReadMemoryByAddress on the lock flash region
the tool RE pointed at (0x3FCC, 0x100230). Stays in the EXTENDED session, which
does not reboot the radio (only the programming session does).

  python uds_explore.py [COMx] [txid_hex] [rxid_hex]
"""
import sys, time
from isotp_uds import UdsClient, show

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    txid = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x727
    rxid = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x72F
    c = UdsClient(port, txid, rxid)
    print(f"read-only UDS explore on {txid:03X}/{rxid:03X}\n")

    r = c.request([0x10, 0x01])
    if r is None:
        print("  radio not responding on 0x72F - it went quiet after the reboot.")
        print("  Re-wake needed: power-cycle while probe_window.py runs, then retry.")
        c.close(); return
    show("DiagSession default (10 01)", r)
    show("Extended session (10 03)", c.request([0x10, 0x03]))
    c.request([0x3E, 0x00])

    print("\n-- security access seed requests (read-only) --")
    for lvl in (0x01, 0x03, 0x05, 0x07, 0x09, 0x0B, 0x11):
        show(f"SecurityAccess seed (27 {lvl:02X})", c.request([0x27, lvl]))

    print("\n-- ReadMemoryByAddress on lock flash region (read-only) --")
    # ALFID 0x14 = 4-byte address, 1-byte size
    show("ReadMem 0x00003FCC len10", c.request([0x23, 0x14, 0x00, 0x00, 0x3F, 0xCC, 0x10]))
    show("ReadMem 0x00100230 len10", c.request([0x23, 0x14, 0x00, 0x10, 0x02, 0x30, 0x10]))
    # some ECUs want ALFID 0x24 (4-byte address, 2-byte size)
    show("ReadMem 0x00003FCC (fmt24)", c.request([0x23, 0x24, 0x00, 0x00, 0x3F, 0xCC, 0x00, 0x10]))

    print("\n-- restore default session --")
    show("DiagSession default (10 01)", c.request([0x10, 0x01]))
    c.close()

if __name__ == "__main__":
    main()
