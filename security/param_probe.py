#!/usr/bin/env python3
"""Find the parameter format of routine 0x0301 (the launch candidate) and fire it.

0x31 01 0301 with no params returned NRC 0x13 (wrong length). We try several
parameter lengths/shapes, all built around our RAM stub address 0x00400000, so
that if 0x0301 turns out to be an erase routine the target is RAM (not flash) and
nothing real gets erased. If it is the SBL-launch, control jumps to our stub
(MOV R0,#0xA5; BX LR) and we look for 0xA5 in the 0x71 reply, or a reboot.

The stub is reloaded before every attempt (a reboot would clear RAM).

  python param_probe.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM  = 0x00400000
STUB = bytes([0xE3,0xA0,0x00,0xA5, 0xE1,0x2F,0xFF,0x1E])

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def download(c, addr, data):
    sz=len(data)
    r=c.request([0x34,0x00,0x44,(addr>>24)&0xFF,(addr>>16)&0xFF,(addr>>8)&0xFF,addr&0xFF,
                 (sz>>24)&0xFF,(sz>>16)&0xFF,(sz>>8)&0xFF,sz&0xFF], timeout=1.0)
    if not r or r[0]!=0x74: return False
    tr=c.request([0x36,0x01]+list(data), timeout=1.5)
    if not tr or tr[0]!=0x76: return False
    ex=c.request([0x37], timeout=1.0)
    return bool(ex and ex[0]==0x77)

def ensure(c):
    for _ in range(3):
        if not establish(c): wake(c,20); continue
        ok,_=unlock(c)
        if ok and download(c, RAM, STUB): return True
    return False

def main():
    port=sys.argv[1] if len(sys.argv)>1 else "COM10"
    c=UdsClient(port,0x727,0x72F)
    if not wake(c): print("no wake; power-cycle during probe."); c.close(); return
    if not ensure(c): print("could not establish+load stub"); c.close(); return
    print(f"ready: unlocked, stub at 0x{RAM:08X}\n")

    A=bytes([0x00,0x40,0x00,0x00])  # 0x00400000 big-endian
    trials=[
        ("no param",               b""),
        ("addr4",                  A),
        ("addr4+len4=8",           A+bytes([0,0,0,8])),
        ("addr4+len4=0x1000",      A+bytes([0,0,0x10,0])),
        ("addr4+len2=8",           A+bytes([0,8])),
        ("len4only=8",             bytes([0,0,0,8])),
        ("addr2",                  bytes([0x40,0x00])),
        ("addr4+len4+crc4",        A+bytes([0,0,0,8])+bytes([0,0,0,0])),
        ("one byte 01",            bytes([0x01])),
        ("addr4+00",               A+bytes([0])),
    ]
    for name,p in trials:
        if not ensure(c):
            print("  (lost session - power-cycle the radio) ");
            if not wake(c,30) or not ensure(c): print("  cannot recover; stopping."); break
        req=[0x31,0x01,0x03,0x01]+list(p)
        r=c.request(req, timeout=1.2)
        if r is None:
            r=c.request(req, timeout=1.2)
        note=""
        if r is None: note="  <== NO RESPONSE (REBOOT? our code may have run)"
        elif 0xA5 in r: note="  <== CONTAINS A5  *** OUR CODE RAN ***"
        elif r[0]==0x71: note="  <== POSITIVE (routine executed)"
        elif r[0]==0x7F and len(r)>=3: note=f"  (NRC {r[2]:02X}{' length' if r[2]==0x13 else ''})"
        print(f"  0301 [{name:18}] {('+'+p.hex().upper()) if p else '(none)':24} -> {hx(r)}{note}")
    c.close()

if __name__ == "__main__":
    main()
