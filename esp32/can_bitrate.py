#!/usr/bin/env python3
"""Detect the radio's CAN bitrate, passively (listen-only).

  python can_bitrate.py [COMx]

Cycles the adapter through the candidate bitrates in LISTEN-ONLY mode and counts
valid frames vs. bus-error flags at each. The real bus rate is the one that
yields clean frames with no bus errors. Ford radio MS-CAN is expected at 125k,
but the TMS470 bootloader could use a different rate, so we check the common set.

Nothing is transmitted; the adapter stays electrically passive the whole time.
"""
import sys, time
from slcan_raw import Slcan

PORT  = sys.argv[1] if len(sys.argv) > 1 else "COM10"
RATES = [125000, 250000, 500000, 1000000, 100000]
DWELL = 3.0   # seconds per rate

def main():
    print(f"port {PORT}, listen-only, {DWELL:.0f}s per rate\n")
    results = []
    for br in RATES:
        s = Slcan(PORT, bitrate=br, listen_only=True)
        s.status()                      # clear flags
        ids = {}
        end = time.time() + DWELL
        total = 0
        while time.time() < end:
            for f in s.poll():
                total += 1
                ids[f.id] = ids.get(f.id, 0) + 1
            time.sleep(0.02)
        st = s.status()
        s.close()
        time.sleep(0.4)
        flag = ""
        if st is not None:
            if st & 0x20: flag += " BUS_ERROR"
            if st & 0x08: flag += " OVERRUN"
            if st & 0x80: flag += " BUS_OFF"
        print(f"{br:>8} bps: {total:5d} frames, {len(ids):3d} unique IDs"
              f"  status=0x{(st or 0):02X}{flag}")
        results.append((br, total, len(ids), st or 0))

    print()
    clean = [r for r in results if r[1] > 0 and not (r[3] & 0xA8)]
    if clean:
        best = max(clean, key=lambda r: r[1])
        print(f"LIKELY BUS RATE: {best[0]} bps "
              f"({best[1]} frames, {best[2]} IDs, no bus errors)")
    else:
        print("No clean traffic at any rate. The bus may be idle (radio not "
              "sending), not wired to CANH/CANL, or the transceiver needs power.")

if __name__ == "__main__":
    main()
