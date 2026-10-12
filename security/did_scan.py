#!/usr/bin/env python3
"""Read-only: scan ReadDataByIdentifier (0x22) for readable DIDs.

Done in the application's extended session (no reboot, no security needed, since
0x22 answered without security before). A DID that returns 0x62 exists and its
data is printed - we are looking for the code, the lock/attempt state, or any
flash-mirroring data. Writes nothing.

  python did_scan.py [COMx]
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RANGES = [
    (0xF100, 0xF1FF), (0xDE00, 0xDEFF), (0xF000, 0xF0FF),
]

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    c = UdsClient(port, 0x727, 0x72F)
    if not wake(c):
        print("radio never woke."); c.close(); return
    if not establish(c):
        wake(c, 20); establish(c)
    ok, info = unlock(c)
    print(f"unlock: {'OK' if ok else 'FAILED'} ({info[2].hex().upper() if ok else info})\n", flush=True)
    if not ok:
        c.close(); return

    found = []
    seen = set()
    tp = time.time()
    for lo, hi in RANGES:
        for did in range(lo, hi + 1):
            if did in seen:
                continue
            seen.add(did)
            if time.time() - tp > 1.0:
                c.request([0x3E, 0x00], timeout=0.15); tp = time.time()
            resp = c.request([0x22, (did >> 8) & 0xFF, did & 0xFF], timeout=0.12)
            if resp and resp[0] == 0x62:
                data = resp[3:]
                txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
                print(f"  DID {did:04X}: {data.hex(' ').upper()}  |{txt}|", flush=True)
                found.append((did, bytes(data)))
    print(f"\n{len(found)} readable DIDs out of {len(seen)} probed.", flush=True)
    c.close()

if __name__ == "__main__":
    main()
