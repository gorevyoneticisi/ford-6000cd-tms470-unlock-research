#!/usr/bin/env python3
"""Passively sniff the radio's CAN bus and summarise what is seen.

  python can_sniff.py [COMx] [bitrate] [seconds]
  python can_sniff.py COM10 125000 20

Listen-only capture. Logs every frame to sniff_<timestamp>.log and prints a live
tail plus, at the end, a table of unique IDs with count, period, and last data.
Use this the moment the radio powers up to catch any boot/announce frames, and
to learn which IDs are active before trying to talk to the bootloader.
"""
import sys, time, os
from collections import defaultdict
from slcan_raw import Slcan

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
BR   = int(sys.argv[2]) if len(sys.argv) > 2 else 125000
SECS = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    logpath = os.path.join(here, time.strftime("sniff_%Y%m%d_%H%M%S.log"))
    log = open(logpath, "w", encoding="utf-8")
    print(f"port {PORT} @ {BR} bps, listen-only, {SECS:.0f}s -> {os.path.basename(logpath)}\n")

    s = Slcan(PORT, bitrate=BR, listen_only=True)
    counts = defaultdict(int)
    firstlast = {}          # id -> [first_t, last_t]
    lastdata = {}
    t0 = time.time()
    shown = 0
    try:
        while time.time() - t0 < SECS:
            for f in s.poll():
                counts[(f.id, f.ext)] += 1
                lastdata[(f.id, f.ext)] = f.data
                fl = firstlast.get((f.id, f.ext))
                if fl is None:
                    firstlast[(f.id, f.ext)] = [f.t, f.t]
                else:
                    fl[1] = f.t
                line = f"{f.t-t0:8.3f}  {f!r}"
                log.write(line + "\n")
                if shown < 40:
                    print(line); shown += 1
                elif shown == 40:
                    print("  ... (further frames only logged to file) ..."); shown += 1
            time.sleep(0.01)
    finally:
        s.close()
        log.close()

    print("\n=== unique IDs ===")
    print(f"{'ID':>9} {'typ':>3} {'count':>6} {'avg ms':>8}  last data")
    for (ident, ext), c in sorted(counts.items()):
        fl = firstlast[(ident, ext)]
        span = fl[1] - fl[0]
        avg = (span * 1000.0 / (c - 1)) if c > 1 else 0.0
        w = 8 if ext else 3
        print(f"{ident:0{w}X}".rjust(9) + f" {'ext' if ext else 'std':>3}"
              f" {c:6d} {avg:8.1f}  {lastdata[(ident,ext)].hex(' ').upper()}")
    print(f"\n{sum(counts.values())} frames, {len(counts)} unique IDs")
    print(f"full log: {logpath}")

if __name__ == "__main__":
    main()
