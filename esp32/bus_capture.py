#!/usr/bin/env python3
"""Capture ALL CAN traffic while another tool (e.g. FORScan via the J2534 adapter)
drives the radio. The ESP32 runs in NORMAL mode with keepalive ON so the radio
stays awake for FORScan, and records every frame with a timestamp.

  python bus_capture.py [COMx] [bitrate] [seconds]
  python bus_capture.py COM10 125000 0      # run until Ctrl-C

Output: bus_capture_<ts>.log  (one line per frame: t, dir, ID, len, data).
Our own 0x7FF keepalive frames are logged too (easy to filter out later).

Use this to record a FORScan session: start it, power-cycle the radio once to
wake it, then run FORScan. The capture is the exact security/flash protocol a
working tool uses, which is what we are missing.
"""
import sys, time, os
from collections import defaultdict
from slcan_raw import Slcan

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
BR   = int(sys.argv[2]) if len(sys.argv) > 2 else 125000
SECS = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0   # 0 = until Ctrl-C

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, time.strftime("bus_capture_%Y%m%d_%H%M%S.log"))
    log = open(path, "w", encoding="utf-8")
    log.write(f"# bus capture {PORT} @ {BR} bps  (keepalive on, normal mode)\n")
    print(f"capturing on {PORT} @ {BR} bps -> {os.path.basename(path)}")
    print("power-cycle the radio once to wake it, then run FORScan. Ctrl-C to stop.\n")

    s = Slcan(PORT, bitrate=BR, listen_only=False)   # normal mode -> keepalive K1 on
    counts = defaultdict(int)
    t0 = time.time()
    last = t0
    n = 0
    try:
        while SECS == 0 or (time.time() - t0) < SECS:
            for f in s.poll():
                t = f.t - t0
                w = 8 if f.ext else 3
                line = f"{t:9.4f}  {f.id:0{w}X} [{len(f.data)}] {f.data.hex(' ').upper()}"
                log.write(line + "\n")
                counts[(f.id, f.ext)] += 1
                n += 1
            if time.time() - last > 2.0:
                log.flush()
                live = ", ".join(f"{i:03X}:{c}" for (i, e), c in
                                 sorted(counts.items(), key=lambda kv: -kv[1])[:8])
                print(f"  [{time.time()-t0:6.1f}s] {n} frames | top: {live}")
                last = time.time()
            time.sleep(0.003)
    except KeyboardInterrupt:
        pass
    finally:
        s.close(); log.flush(); log.close()

    print(f"\n{n} frames, {len(counts)} unique IDs -> {path}")
    print("unique IDs seen:")
    for (i, e), c in sorted(counts.items()):
        w = 8 if e else 3
        print(f"  {i:0{w}X}  x{c}")

if __name__ == "__main__":
    main()
