#!/usr/bin/env python3
"""Test whether ECUReset (0x11) diverts execution to RAM instead of booting flash.

Mechanism (untested until now, different from RoutineControl): some bootloaders
check a RAM region for a valid downloaded image when the CPU resets, before
falling through to the flash application. We've never sent 0x11 in this whole
investigation. This is a standard, benign UDS service - worst case is an
ordinary reset (which already happens constantly in this workflow).

Detection: load an infinite-loop stub (ARM `B .` = branch-to-self, opcode
EA FF FF FE) at RAM 0x00400000, then ECUReset. If the CPU boots flash normally,
the radio comes back exactly as any reset does. If the CPU jumped into our loop,
it hangs forever - CAN goes silent and (if the SCI tap is still connected) the
SCI comms heartbeat stops, until a power-cycle clears RAM. We check BOTH signals.

  python ecureset_exec_test.py [COMx]
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM = 0x00400000
LOOP_STUB = bytes([0xEA, 0xFF, 0xFF, 0xFE])   # B . (branch to self, infinite loop)

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

    print("== Step 1: is ECUReset (0x11) even supported? (safe query) ==")
    r = c.request([0x11, 0x01], timeout=1.0)   # hardReset
    print(f"  0x11 01 (hardReset) -> {hx(r)}")
    if r and r[0] == 0x7F and len(r) >= 3 and r[2] in (0x11, 0x12):
        print("  ECUReset NOT supported in this session. Stopping - nothing else to try here.")
        c.close(); return
    if r and r[0] == 0x51:
        print("  POSITIVE - 0x11 01 is a real, working reset. Continuing to test it WITH a stub loaded.")
    print("  (continuing)\n")

    print("== Step 2: re-establish session + load infinite-loop stub at RAM ==")
    if not establish(c): wake(c, 20); establish(c)
    ok, info = unlock(c)
    if not ok: print(f"unlock FAILED: {info}"); c.close(); return
    okd, dr = download(c, RAM, LOOP_STUB)
    print(f"  stub -> RAM 0x{RAM:08X}: {'OK' if okd else 'FAILED '+hx(dr)}")
    if not okd: c.close(); return

    print("\n== Step 3: send ECUReset 0x11 01 (hardReset) with stub loaded ==")
    r2 = c.request([0x11, 0x01], timeout=1.5)
    print(f"  0x11 01 -> {hx(r2)}")

    print("\n== Step 4: try to re-establish communication (normal reset = radio comes back) ==")
    time.sleep(1.0)
    recovered = False
    for attempt in range(5):
        if wake(c, 6):
            recovered = True
            break
    if recovered:
        print("  radio ACKing again - CAN came back on its own (consistent with a NORMAL reset to flash,")
        print("  i.e. the stub probably did NOT run - but check the SCI capture below to be sure)")
    else:
        print("  *** radio did NOT come back on CAN after repeated tries ***")
        print("  *** this is CONSISTENT with the CPU being stuck in our RAM loop ***")
        print("  *** POWER-CYCLE THE RADIO NOW to recover (clears RAM, reboots to flash) ***")

    c.close()
    print("\nNEXT: run esp32/sci_monitor.py in 'monitor 57600' mode RIGHT NOW (before power-cycling)")
    print("to check whether the SCI heartbeat is silent (stub running) or still ticking (normal boot).")

if __name__ == "__main__":
    main()
