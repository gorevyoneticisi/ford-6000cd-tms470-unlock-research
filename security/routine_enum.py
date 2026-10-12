#!/usr/bin/env python3
"""Enumerate RoutineControl (0x31) routine IDs SAFELY.

Uses ONLY subfunction 0x03 (requestRoutineResults), which queries a routine's
result and CANNOT start or erase anything. Goal: discover which routine IDs the
PBL knows (so we can later pick the "start downloaded code / jump to RAM" one and
AVOID the erase routines) without triggering any of them.

NRC meaning per ID:
  0x31 requestOutOfRange / 0x12 subFunctionNotSupported -> ID not present
  0x22 conditionsNotCorrect / 0x24 requestSequenceError  -> ID EXISTS (not run yet)
  0x7x positive                                          -> ID exists and returned

  python routine_enum.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

# Curated candidate IDs. 0xFFxx is the Ford erase/program-control family (we only
# QUERY them here with 0x03, never start). The rest are common SBL/exec/launch IDs.
IDS = [0x0000, 0x0010, 0x0011, 0x0100, 0x0200, 0x0201, 0x0202, 0x0203, 0x0204,
       0x0205, 0x0206, 0x0300, 0x0301, 0x0302, 0x0303, 0x0304,
       0x1010, 0x1234, 0x3101, 0xC000, 0xD000, 0xDF00, 0xE000, 0xE001,
       0xFF00, 0xFF01, 0xFF02, 0xFF03, 0xFFFF]

def hx(r):
    return r.hex(' ').upper() if r else "(no response)"

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

    # Does the PBL support startRoutine/stop/results at all? Query with a clearly
    # bogus ID using 0x03 (safe). 0x12 = subfunc unsupported; 0x31 = id out of range.
    probe = c.request([0x31, 0x03, 0xAB, 0xCD], timeout=0.8)
    print(f"0x31 03 ABCD (subfunction probe) -> {hx(probe)}\n")

    present = []
    for rid in IDS:
        r = c.request([0x31, 0x03, (rid >> 8) & 0xFF, rid & 0xFF], timeout=0.8)
        tag = ""
        if r and r[0] == 0x71:
            tag = "  <== EXISTS (positive result)"; present.append(rid)
        elif r and r[0] == 0x7F and len(r) >= 3 and r[2] in (0x22, 0x24, 0x33):
            tag = f"  <== EXISTS (NRC {r[2]:02X})"; present.append(rid)
        print(f"  {rid:04X}: {hx(r)}{tag}")
    print("\nlikely-present routine IDs:", ", ".join(f"{x:04X}" for x in present) or "none clearly identified")
    c.close()

if __name__ == "__main__":
    main()
