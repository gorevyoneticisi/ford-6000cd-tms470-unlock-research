#!/usr/bin/env python3
"""Enumerate valid RoutineControl IDs SAFELY via stopRoutine (0x31 02).

startRoutine (0x01) runs a routine, so we must not sweep it blindly. stopRoutine
(0x02) on a routine that is not running cannot start or erase anything - it just
reveals whether the ID is recognised. We use it to map the valid IDs first, then
decide which one is the SBL-launch (and avoid any erase routine).

Responses per ID with 0x31 02 <id>:
  7F 31 31 -> ID not recognised (out of range)
  7F 31 12 -> stopRoutine subfunction not supported (abort, 0x02 unusable)
  7F 31 22/24 or 71 02 .. -> ID RECOGNISED (valid routine)

  python routine_enum2.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def stop(c, rid):
    return c.request([0x31, 0x02, (rid >> 8) & 0xFF, rid & 0xFF], timeout=0.6)

def recognised(r):
    if not r: return False
    if r[0] == 0x71: return True
    if r[0] == 0x7F and len(r) >= 3 and r[2] in (0x22, 0x24, 0x33, 0x21): return True
    return False

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    c = UdsClient(port, 0x727, 0x72F)
    if not wake(c):
        print("radio never woke; power-cycle during the wake probe."); c.close(); return
    if not establish(c):
        wake(c, 20); establish(c)
    ok, info = unlock(c)
    if not ok:
        print(f"unlock FAILED: {info}"); c.close(); return
    print(f"UNLOCKED (seed {info[0]:06X})\n")

    probe = stop(c, 0xABCD)
    print(f"0x31 02 ABCD (stopRoutine support) -> {hx(probe)}")
    if probe and probe[0] == 0x7F and len(probe) >= 3 and probe[2] == 0x12:
        print("stopRoutine NOT supported; cannot enumerate safely this way. Stopping.")
        c.close(); return
    print("stopRoutine usable -> sweeping IDs (safe, runs nothing)...\n")

    found = []
    ranges = list(range(0x0000, 0x0400)) + list(range(0xFE00, 0x10000))
    extra  = [0xDE00, 0xDF00, 0xE000, 0xE200, 0xF000, 0xF001, 0x1000, 0x1001, 0x8000]
    for rid in ranges + extra:
        r = stop(c, rid)
        if recognised(r):
            found.append((rid, hx(r)))
            print(f"  VALID {rid:04X}: {hx(r)}")
    print("\nrecognised routine IDs:", ", ".join(f"{x:04X}" for x, _ in found) or "none found in swept set")
    c.close()

if __name__ == "__main__":
    main()
