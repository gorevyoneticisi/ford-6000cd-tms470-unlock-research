#!/usr/bin/env python3
"""Step 1: probe whether RoutineControl StartRoutine (0x31 01) is supported.

Sends a few DELIBERATELY BOGUS routine IDs with subfunction 0x01 (startRoutine)
and reports the response. This loads/runs NO code. It only tells us:
  7F 31 12 -> startRoutine subfunction not supported (path closed)
  7F 31 31 -> supported, but that ID is invalid  (path OPEN; we need the real ID)
  7F 31 22/24 -> supported, conditions/sequence issue
  71 01 .. -> that ID is actually a real routine (unexpected)
Bogus IDs chosen to avoid the Ford erase/program family (0xFFxx, 0x02xx, 0x03xx).

  python routine_probe.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

def hx(r): return r.hex(' ').upper() if r else "(no response)"

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

    print("== 0x31 01 <bogus id> (startRoutine support probe, runs nothing) ==")
    for rid in (0xABCD, 0x1234, 0x5A5A):
        r = c.request([0x31, 0x01, (rid >> 8) & 0xFF, rid & 0xFF], timeout=1.0)
        note = ""
        if r and r[0] == 0x7F and len(r) >= 3:
            note = {0x12: "startRoutine NOT supported", 0x31: "supported, ID invalid (path OPEN)",
                    0x22: "supported, conditionsNotCorrect", 0x24: "supported, requestSequenceError",
                    0x13: "incorrect length/format"}.get(r[2], f"NRC {r[2]:02X}")
        elif r and r[0] == 0x71:
            note = "POSITIVE - that ID is a real routine (!)"
        print(f"  id {rid:04X}: {hx(r)}   {note}")
    c.close()

if __name__ == "__main__":
    main()
