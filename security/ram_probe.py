#!/usr/bin/env python3
"""Probe whether the PBL exposes RAM transfer (the untested bootloader-upload path).

Background: every earlier 0x34/0x35 test targeted FLASH addresses, which correctly
returned requestOutOfRange. The SEGGER J-Link thread revealed the TMS470R1 SRAM base
is 0x00400000. If the PBL accepts RequestDownload (0x34) to RAM, we can later upload a
small ARM7-BE stub that copies the lock-region flash (0x3FB0 / 0x100230) into RAM and
read it back via 0x35. THIS SCRIPT IS READ-ONLY / NON-DESTRUCTIVE:
  - 0x35 RequestUpload   : pure read.
  - 0x34 RequestDownload : only NEGOTIATES a transfer; we immediately 0x37-close it and
                           send NO 0x36 TransferData, so nothing is written anywhere.
No flash write is attempted anywhere in this script.

  python ram_probe.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock, upload_read

RAM_BASE = 0x00400000          # TMS470R1 internal SRAM base (from SEGGER J-Link thread)

def hx(r):
    return r.hex(' ').upper() if r else "(no response)"

def download_probe(c, addr, size, alfid):
    """0x34 RequestDownload acceptance test. Negotiate only, then close with 0x37.
    alfid nibble layout: high = size length (bytes), low = address length (bytes)."""
    alen = alfid & 0x0F
    slen = (alfid >> 4) & 0x0F
    req = [0x34, 0x00, alfid]
    req += [(addr >> (8 * (alen - 1 - i))) & 0xFF for i in range(alen)]
    req += [(size >> (8 * (slen - 1 - i))) & 0xFF for i in range(slen)]
    r = c.request(req, timeout=1.0)
    ok = bool(r and r[0] == 0x74)
    if ok:
        c.request([0x37], timeout=0.5)   # close the negotiated transfer, write nothing
    return ok, r

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
    seed, key, resp = info
    print(f"UNLOCKED (seed {seed:06X} key {key.hex().upper()})\n")

    print("== 1) 0x35 RequestUpload FROM RAM 0x%08X (read-only) ==" % RAM_BASE)
    for size in (0x10, 0x40):
        data, first = upload_read(c, RAM_BASE, size)
        if data is not None:
            print(f"  size 0x{size:02X}: GOT {len(data)} bytes -> {data.hex(' ').upper()}")
        else:
            print(f"  size 0x{size:02X}: upload refused -> {hx(first)}")

    print("\n== 2) 0x34 RequestDownload TO RAM 0x%08X (negotiate-only, closed) ==" % RAM_BASE)
    for alfid in (0x14, 0x24, 0x44):
        ok2, r = download_probe(c, RAM_BASE, 0x40, alfid)
        verdict = "ACCEPTED" if ok2 else "refused"
        print(f"  ALFID 0x{alfid:02X}: {verdict} -> {hx(r)}")

    print("\n== 3) 0x35 RequestUpload from community lock address 0x3FB0 (80 bytes) ==")
    data, first = upload_read(c, 0x00003FB0, 0x50)
    if data is not None:
        print(f"  GOT {len(data)} bytes:\n    {data.hex(' ').upper()}")
    else:
        print(f"  refused -> {hx(first)}")

    c.close()

if __name__ == "__main__":
    main()
