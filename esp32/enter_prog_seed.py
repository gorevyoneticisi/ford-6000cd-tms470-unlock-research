#!/usr/bin/env python3
"""Enter the programming session (one reboot) and capture a security seed.

Read-only with respect to flash: it only requests seeds (service 27 odd
subfunctions). It sends the programming session once (which reboots the radio
into its bootloader), then repeatedly asks for a seed while keeping the bus
active, so the bootloader's CAN stays awake. Prints every distinct response.

  python enter_prog_seed.py [COMx] [txid_hex] [rxid_hex]
"""
import sys, time
from isotp_uds import UdsClient, show, nrc

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    txid = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x727
    rxid = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x72F
    c = UdsClient(port, txid, rxid)

    r = c.request([0x10, 0x01])
    if r is None:
        print("radio not responding (asleep). Re-wake with probe_window.py + power-cycle, then retry.")
        c.close(); return
    show("default session (10 01)", r)

    print("\nsending programming session (10 02) - radio reboots into bootloader now...\n")
    show("prog session (10 02)", c.request([0x10, 0x02], timeout=1.0))

    print("\npost-reboot: requesting seeds while keeping CAN alive (~14s)\n")
    t0 = time.time()
    seen = {}
    last_tp = 0
    alive = False
    while time.time() - t0 < 14:
        now = time.time()
        if now - last_tp > 0.8:
            c.request([0x3E, 0x00], timeout=0.2)   # keep session / bus alive
            last_tp = now
        for lvl in (0x01, 0x05, 0x09):
            resp = c.request([0x27, lvl], timeout=0.25)
            if resp is None:
                continue
            alive = True
            key = (lvl, bytes(resp))
            if key not in seen:
                seen[key] = now - t0
                if resp[0] == 0x67:
                    print(f"  [{now-t0:4.1f}s] SEED level {lvl:02X}: {resp[2:].hex(' ').upper()}  "
                          f"(full: {resp.hex(' ').upper()})")
                elif resp[0] == 0x7F:
                    print(f"  [{now-t0:4.1f}s] 27 {lvl:02X} -> NEG {nrc(resp[2])}")
                else:
                    print(f"  [{now-t0:4.1f}s] 27 {lvl:02X} -> {resp.hex(' ').upper()}")

    if not alive:
        print("  no response after the reboot - the bootloader's CAN did not come up on this")
        print("  endpoint, or it needs a power-cycle wake. We can re-wake and scan the bootloader IDs.")
    print("\nrestoring default session")
    c.request([0x10, 0x01], timeout=0.5)
    c.close()

if __name__ == "__main__":
    main()
