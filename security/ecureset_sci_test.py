#!/usr/bin/env python3
"""ECUReset-diverts-to-RAM test, with the SCI heartbeat monitored LIVE through the
same reset, not after the fact (the previous version's CAN-recovery-only check was
ambiguous: the AWD hardware watchdog could catch a hung stub and reboot into flash
within the same ~10s window, looking identical to "never diverted" from CAN alone).

This script enables the SCI sniffer (U57600) FIRST so it streams in parallel with
every UDS exchange (slcan_raw safely ignores "@" lines, they are not t/T/r/R CAN
frames), then loads an infinite-loop stub (ARM `B .`, EA FF FF FE) at RAM
0x00400000, fires ECUReset 0x11 01, and prints a live timestamped log of every SCI
byte for ~15s afterward. A normal reset = the APK heartbeat keeps ticking with at
most a brief gap. A diverted-to-our-loop reset = a LONGER silence (stub hangs until
AWD catches it) before the heartbeat resumes, or does not resume without a manual
power-cycle.

  python ecureset_sci_test.py [COMx]
"""
import os, sys, time, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM = 0x00400000
LOOP_STUB = bytes([0xEA, 0xFF, 0xFF, 0xFE])   # B . (infinite loop)

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def download(c, addr, data):
    sz = len(data)
    r = c.request([0x34,0x00,0x44,(addr>>24)&0xFF,(addr>>16)&0xFF,(addr>>8)&0xFF,addr&0xFF,
                   (sz>>24)&0xFF,(sz>>16)&0xFF,(sz>>8)&0xFF,sz&0xFF], timeout=1.0)
    if not r or r[0]!=0x74: return False, r
    tr = c.request([0x36,0x01]+list(data), timeout=1.5)
    if not tr or tr[0]!=0x76: return False, tr
    ex = c.request([0x37], timeout=1.0)
    return (bool(ex and ex[0]==0x77)), ex

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    c = UdsClient(port, 0x727, 0x72F)
    if not wake(c): print("no wake; power-cycle during probe."); c.close(); return
    if not establish(c): wake(c,20); establish(c)
    ok, info = unlock(c)
    if not ok: print(f"unlock FAILED: {info}"); c.close(); return
    print(f"UNLOCKED (seed {info[0]:06X})\n")

    print("== enabling SCI sniffer (U57600) on the same link ==")
    c.s.ser.write(b"U57600\r"); time.sleep(0.2); c.s.ser.reset_input_buffer()

    print("== baseline: 3s of SCI before touching anything ==")
    t0 = time.time()
    saw_baseline = False
    while time.time() - t0 < 3:
        n = c.s.ser.in_waiting
        if n:
            raw = c.s.ser.read(n)
            if b"@" in raw:
                saw_baseline = True
    print(f"  baseline SCI activity seen: {saw_baseline}")
    if not saw_baseline:
        print("  WARNING: no SCI activity before we even start - tap may be disconnected.")
        print("  Continuing anyway (CAN-side evidence still meaningful on its own).\n")

    print("== loading infinite-loop stub at RAM 0x%08X ==" % RAM)
    okd, dr = download(c, RAM, LOOP_STUB)
    print(f"  stub load: {'OK' if okd else 'FAILED '+hx(dr)}")
    if not okd: c.close(); return

    print("\n== firing ECUReset 0x11 01 and watching SCI live for 15s ==")
    c.s.ser.reset_input_buffer()
    t_fire = time.time()
    r = c.request([0x11, 0x01], timeout=1.5)
    print(f"  0x11 01 response -> {hx(r)}  (at t+{time.time()-t_fire:.2f}s)")

    last_activity = None
    first_gap_start = None
    gaps = []
    end = time.time() + 15
    buf = b""
    while time.time() < end:
        n = c.s.ser.in_waiting
        now = time.time() - t_fire
        if n:
            raw = c.s.ser.read(n)
            buf += raw
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                if line.startswith(b"@"):
                    if last_activity is not None and first_gap_start is None:
                        pass
                    if last_activity is not None:
                        gap = now - last_activity
                        if gap > 0.5:
                            gaps.append((last_activity, gap))
                    last_activity = now
        time.sleep(0.01)
    print(f"\n  last SCI activity before reset-fire: baseline only")
    print(f"  SCI activity timeline after reset (gaps > 0.5s shown):")
    if not gaps:
        print("    no gaps > 0.5s detected - heartbeat looks CONTINUOUS (consistent with a NORMAL")
        print("    reset straight back to flash; the stub most likely did NOT run)")
    else:
        for t, g in gaps:
            print(f"    silence of {g:.2f}s ending at t+{t:.2f}s")
        longest = max(g for _, g in gaps)
        print(f"    longest gap: {longest:.2f}s", end="  ")
        if longest > 2.0:
            print("<<< SIGNIFICANT - consistent with the stub RUNNING until the AWD watchdog caught it")
        else:
            print("(short - likely just normal reset/reboot jitter, not conclusive either way)")

    print("\n== trying to re-establish CAN session now ==")
    recovered = wake(c, 10)
    print(f"  CAN recovered: {recovered}")
    c.close()

if __name__ == "__main__":
    main()
