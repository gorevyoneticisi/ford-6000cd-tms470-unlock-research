#!/usr/bin/env python3
"""Sweep the rest of the startRoutine ID space with NO parameters to find all
recognised routines. Safe: a routine that needs an address returns 7F 31 13
(length) without acting, as 0x0301 did. We just want to map which IDs exist.

Known so far: 0301 (flash op, 4-byte addr), FF01 (checkProgrammingDependencies).
Looking for another recognised ID (ideally a RAM/SBL launch).

  7F 31 31 -> unknown      7F 31 13 -> recognised, needs params
  71 .. / other NRC        -> recognised

  python routine_sweep_full.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def ensure(c):
    for _ in range(3):
        if establish(c):
            ok,_=unlock(c)
            if ok: return True
        wake(c,25)
    return False

def main():
    port=sys.argv[1] if len(sys.argv)>1 else "COM10"
    c=UdsClient(port,0x727,0x72F)
    if not wake(c): print("no wake; power-cycle during probe."); c.close(); return
    if not ensure(c): print("no session"); c.close(); return
    print("ready; sweeping (prints recognised IDs only)...\n")
    ranges=[(0x0400,0x1000),(0x1000,0x1200),(0x2000,0x2100),(0x3000,0x3100),
            (0x8000,0x8100),(0xD000,0xD100),(0xDE00,0xE300),(0xF000,0x10000)]
    found=[]; done=0
    for lo,hi in ranges:
        for rid in range(lo,hi):
            r=c.request([0x31,0x01,(rid>>8)&0xFF,rid&0xFF], timeout=0.5)
            if r is None:
                r=c.request([0x31,0x01,(rid>>8)&0xFF,rid&0xFF], timeout=0.5)
                if r is None:
                    if not ensure(c):
                        wake(c,30); ensure(c)
                    continue
            if not (r[0]==0x7F and len(r)>=3 and r[2]==0x31):
                found.append((rid,hx(r)))
                print(f"  RECOGNISED {rid:04X}: {hx(r)}")
            done+=1
            if done % 1000 == 0: print(f"   ...{done} ids swept")
    print("\nrecognised IDs:", ", ".join(f"{x:04X}" for x,_ in found) or "none new")
    c.close()

if __name__ == "__main__":
    main()
