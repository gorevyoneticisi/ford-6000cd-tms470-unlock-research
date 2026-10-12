#!/usr/bin/env python3
"""Find the SBL-launch routine by loading a marker stub into RAM and sweeping
startRoutine IDs. This PBL exposes no flash access (all flash R/W was rejected as
out-of-range), so startRoutine has no flash routine to invoke; the expected worst
case is a recoverable reboot. User has authorised this on their own hardware.

Stub at 0x00400000 (ARM7, big-endian):  MOV R0,#0xA5 ; BX LR
  E3 A0 00 A5   E1 2F FF 1E
If the PBL CALLS the launch routine, our stub returns and the 0x71 response may
carry 0xA5 -> that ID runs OUR code. If it JUMPS, control may not return and the
watchdog reboots (session drops) -> that ID also launched us. Bogus IDs -> 7F 31 31.

  python exec_test.py [COMx]
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM = 0x00400000
STUB = bytes([0xE3,0xA0,0x00,0xA5, 0xE1,0x2F,0xFF,0x1E])

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
    print(f"UNLOCKED (seed {info[0]:06X})")
    okd, r = download(c, RAM, STUB)
    print(f"stub -> RAM 0x{RAM:08X}: {'OK' if okd else 'FAILED '+hx(r)}\n")
    if not okd: c.close(); return

    cand = [0x0301,0x0304,0x0302,0x0303,0x0305,0x0306,0x0202,0x0203,0x0201,0x0204,0x0205,
            0x0300,0x0200,0x0100,0x0101,0x0001,0x0002,0x0003,0x0000,0x0400,0x0401,
            0xFF01,0xFF02,0x0D01,0x0310,0x0320,0x1000,0x0010,0x0011,0xDE00,0xDF00,0xE000,0x0A00]
    swept = list(dict.fromkeys(cand + list(range(0x0000,0x0400))))
    print(f"sweeping {len(swept)} startRoutine IDs (candidates first)...")
    valids=[]
    for rid in swept:
        r = c.request([0x31,0x01,(rid>>8)&0xFF,rid&0xFF], timeout=0.8)
        if r is None:
            r2 = c.request([0x31,0x01,(rid>>8)&0xFF,rid&0xFF], timeout=0.8)
            if r2 is None:
                print(f"  {rid:04X}: NO RESPONSE x2  <== possible REBOOT (our code ran?) - stopping")
                break
            r = r2
        if r[0]==0x7F and len(r)>=3 and r[2]==0x31:
            continue
        tag = "  <== CONTAINS A5 (OUR CODE RAN)" if (0xA5 in r) else ""
        if r[0]==0x7F: tag = tag or f"  (NRC {r[2]:02X})"
        print(f"  VALID {rid:04X}: {hx(r)}{tag}")
        valids.append((rid, hx(r)))
    print("\nvalid IDs:", ", ".join(f"{x:04X}" for x,_ in valids) or "none")
    c.close()

if __name__ == "__main__":
    main()
