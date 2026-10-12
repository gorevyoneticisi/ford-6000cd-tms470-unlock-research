#!/usr/bin/env python3
"""Confirm the full RAM download path: 0x34 (accepted earlier) + 0x36 + 0x37.

This WRITES ONLY TO RAM at 0x00400000 (the address the PBL accepted for download).
RAM is volatile: the worst realistic outcome is that the PBL is disturbed and the
radio reboots (recoverable by power-cycle). NOTHING is written to flash. We cannot
read the bytes back (0x35 upload is refused), so success is judged by the PBL
returning positive 0x76 (TransferData) and 0x74/0x77 for the exit.

  python ram_download_test.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM = 0x00400000

def hx(r):
    return r.hex(' ').upper() if r else "(no response)"

def req_download(c, addr, size):
    """0x34 with ALFID 0x44 (4-byte addr + 4-byte size). Returns (maxblock, resp)."""
    r = c.request([0x34, 0x00, 0x44,
                   (addr >> 24) & 0xFF, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF,
                   (size >> 24) & 0xFF, (size >> 16) & 0xFF, (size >> 8) & 0xFF, size & 0xFF],
                  timeout=1.0)
    if not r or r[0] != 0x74:
        return None, r
    lfid = r[1] >> 4            # number of bytes in the maxblock field
    mb = int.from_bytes(bytes(r[2:2 + lfid]), "big") if lfid else 0
    return mb, r

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

    # A recognizable 16-byte payload (also a valid ARM7 'BX LR' return word first,
    # big-endian E1 2F FF 1E, in case we later execute it). Not executed here.
    payload = bytes([0xE1, 0x2F, 0xFF, 0x1E]) + bytes.fromhex("DEADBEEF11223344AABBCCDD")

    print(f"== 0x34 RequestDownload to RAM 0x{RAM:08X}, {len(payload)} bytes ==")
    mb, r = req_download(c, RAM, len(payload))
    print(f"  0x34 -> {hx(r)}   maxblock={mb}")
    if mb is None:
        print("  download refused; stopping."); c.close(); return

    print("== 0x36 TransferData (block seq 1) ==")
    tr = c.request([0x36, 0x01] + list(payload), timeout=1.5)
    print(f"  0x36 -> {hx(tr)}")

    print("== 0x37 RequestTransferExit ==")
    ex = c.request([0x37], timeout=1.0)
    print(f"  0x37 -> {hx(ex)}")

    good = tr and tr[0] == 0x76 and ex and ex[0] == 0x77
    print("\nRESULT:", "RAM LOAD PATH WORKS (code can be placed in RAM)" if good
          else "load path incomplete; see responses above")
    c.close()

if __name__ == "__main__":
    main()
