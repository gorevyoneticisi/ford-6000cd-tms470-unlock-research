#!/usr/bin/env python3
"""Retry 0x35 RequestUpload with the ALFID the PBL actually accepted for download
(0x44 = 4-byte address + 4-byte size), which earlier upload tests never used.

Pure read, writes nothing. If any of these return 0x75 we can read flash with no
code execution at all.

  python ram_upload_retry.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

def hx(r):
    return r.hex(' ').upper() if r else "(no response)"

def upload(c, addr, size, alfid):
    alen = alfid & 0x0F
    slen = (alfid >> 4) & 0x0F
    req = [0x35, 0x00, alfid]
    req += [(addr >> (8 * (alen - 1 - i))) & 0xFF for i in range(alen)]
    req += [(size >> (8 * (slen - 1 - i))) & 0xFF for i in range(slen)]
    r = c.request(req, timeout=1.0)
    data = None
    if r and r[0] == 0x75:
        # try to pull the data via 0x36
        data = bytearray(); bsc = 1
        while len(data) < size:
            tr = c.request([0x36, bsc & 0xFF], timeout=1.0)
            if not tr or tr[0] != 0x76:
                break
            data += tr[2:]; bsc += 1
            if len(tr) <= 2:
                break
        c.request([0x37], timeout=0.5)
    return r, (bytes(data) if data is not None else None)

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

    targets = [("RAM 0x00400000", 0x00400000, 0x10),
               ("flash 0x3FB0", 0x00003FB0, 0x50),
               ("flash 0x100230", 0x00100230, 0x28)]
    for alfid in (0x44, 0x24):
        print(f"-- 0x35 RequestUpload, ALFID 0x{alfid:02X} --")
        for name, addr, size in targets:
            r, data = upload(c, addr, size, alfid)
            if data:
                print(f"  {name}: GOT {len(data)} bytes -> {data.hex(' ').upper()}")
            else:
                print(f"  {name}: {hx(r)}")
    c.close()

if __name__ == "__main__":
    main()
