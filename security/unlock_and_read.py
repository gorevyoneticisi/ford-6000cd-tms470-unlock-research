#!/usr/bin/env python3
"""Unlock SecurityAccess with a known secret, then READ-ONLY explore the flash.

Writes nothing. Uses a recovered 5-byte secret to pass SecurityAccess in one
shot, then tries ReadMemoryByAddress on the lock region the tool RE pointed at
(0x3FCC, 0x100230) and reads a few identification DIDs.

The actual secret this project found for its own radio is NOT included here
(see DOCUMENTATION.md for how it was found: brute-forcing jakka351's public
keybag - github.com/jakka351/Ford-ECU-Bruteforcer - against the module). Set
your own below if you've run that same search against your own hardware.

  python unlock_and_read.py [COMx]
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient, nrc, show
from keygen_ford import key_bytes
from seedkey_brute import wake, establish

SECRET = bytes.fromhex("0000000000")  # replace with your own recovered secret

def unlock(c, tries=20):
    """Robust unlock: retry seed+key until it takes (the radio drops the odd
    request). Returns (ok, info). Stops early on rate-limit NRCs 0x36/0x37."""
    last = None
    for _ in range(tries):
        r = c.request([0x27, 0x01], timeout=0.4)
        if not (r and r[0] == 0x67 and len(r) >= 5):
            last = r
            continue
        seed = (r[2] << 16) | (r[3] << 8) | r[4]
        key = key_bytes(seed, SECRET)
        resp = c.request([0x27, 0x02, key[0], key[1], key[2]], timeout=0.5)
        if resp and resp[0] == 0x67 and resp[1] == 0x02:
            return True, (seed, key, resp)
        last = (seed, key, resp)
        if resp and resp[0] == 0x7F and len(resp) >= 3 and resp[2] in (0x36, 0x37):
            break
    return False, last

def readmem(c, addr, size, alfid=0x14):
    # ALFID 0x14 = 4-byte address, 1-byte size
    req = [0x23, alfid, (addr >> 24) & 0xFF, (addr >> 16) & 0xFF,
           (addr >> 8) & 0xFF, addr & 0xFF, size & 0xFF]
    return c.request(req, timeout=1.0)

def upload_read(c, addr, size):
    """RequestUpload (0x35) + TransferData (0x36) read. Returns (data, first_resp)."""
    req = [0x35, 0x00, 0x14, (addr >> 24) & 0xFF, (addr >> 16) & 0xFF,
           (addr >> 8) & 0xFF, addr & 0xFF, size & 0xFF]
    r = c.request(req, timeout=1.0)
    if not r or r[0] != 0x75:
        return None, r
    data = bytearray(); bsc = 1
    while len(data) < size:
        tr = c.request([0x36, bsc & 0xFF], timeout=1.0)
        if not tr or tr[0] != 0x76:
            break
        data += tr[2:]
        bsc += 1
        if len(tr) <= 2:
            break
    c.request([0x37], timeout=0.5)   # RequestTransferExit
    return bytes(data[:size]), r

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    c = UdsClient(port, 0x727, 0x72F)
    if not wake(c):
        print("radio never woke; power-cycle during the wake probe."); c.close(); return
    if not establish(c):
        wake(c, 20); establish(c)
    print("bootloader ready; unlocking security with known secret...")
    ok, info = unlock(c)
    if not ok:
        print(f"  unlock FAILED: {info}"); c.close(); return
    seed, key, resp = info
    print(f"  UNLOCKED (seed {seed:06X} key {key.hex().upper()} -> {resp.hex().upper()})\n")

    print("-- read-only flash probes (RequestUpload 0x35) --")
    for name, addr, size in [("0x100230", 0x00100230, 0x28), ("0x3FCC", 0x00003FCC, 0x30)]:
        data, first = upload_read(c, addr, size)
        if data is not None:
            print(f"  {name}: {len(data)} bytes")
            print(f"    {data.hex(' ').upper()}")
            txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
            print(f"    |{txt}|")
        else:
            fr = first.hex(' ').upper() if first else "(no response)"
            print(f"  {name}: upload not available -> {fr}")
    c.close()

if __name__ == "__main__":
    main()
