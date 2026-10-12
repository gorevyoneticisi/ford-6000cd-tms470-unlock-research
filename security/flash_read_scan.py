#!/usr/bin/env python3
"""Read-only: find which flash addresses RequestUpload (0x35) will read.

Unlocks with the known secret, then probes a spread of addresses with a tiny
upload request (16 bytes). 0x75 = readable (then it reads and prints the bytes);
0x31 = out of range. This maps the readable window without writing anything.

  python flash_read_scan.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient, nrc
from seedkey_brute import wake, establish
from unlock_and_read import unlock, upload_read

ADDRS = [0x00000000, 0x00000800, 0x00001000, 0x00003FCC, 0x00004000, 0x00008000,
         0x0000C000, 0x00010000, 0x00020000, 0x00040000, 0x00080000, 0x000F0000,
         0x00100000, 0x00100200, 0x00100230, 0x00104000, 0x00108000, 0x00110000,
         0x00180000, 0x00200000, 0x00300000, 0x00380000, 0x003F0000, 0x00400000]

def try_upload(c, addr, size=0x10):
    req = [0x35, 0x00, 0x14, (addr >> 24) & 0xFF, (addr >> 16) & 0xFF,
           (addr >> 8) & 0xFF, addr & 0xFF, size & 0xFF]
    return c.request(req, timeout=0.6)

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    c = UdsClient(port, 0x727, 0x72F)
    if not wake(c):
        print("radio never woke."); c.close(); return
    if not establish(c):
        wake(c, 20); establish(c)
    ok, info = unlock(c)
    if not ok:
        print(f"unlock failed: {info}"); c.close(); return
    print(f"UNLOCKED {info[2].hex().upper()}\n")

    readable = []
    for a in ADDRS:
        r = try_upload(c, a)
        if r is None:
            tag = "(no resp)"
        elif r[0] == 0x75:
            tag = "READABLE (0x75)"
            readable.append(a)
            c.request([0x37], timeout=0.3)   # close the upload we just opened
        elif r[0] == 0x7F:
            tag = "NEG " + nrc(r[2])
        else:
            tag = r.hex().upper()
        print(f"  {a:08X} -> {tag}")

    if readable:
        print("\n-- reading the readable regions --")
        for a in readable:
            data, _ = upload_read(c, a, 0x20)
            if data:
                txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
                print(f"  {a:08X}: {data.hex(' ').upper()}  |{txt}|")
    else:
        print("\nNo address was readable via 0x35. The bootloader likely blocks")
        print("uploads entirely (write-only), so the tool reads via its own channel.")
    c.close()

if __name__ == "__main__":
    main()
