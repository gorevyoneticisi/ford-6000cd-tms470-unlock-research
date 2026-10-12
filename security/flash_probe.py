#!/usr/bin/env python3
"""Read-only: map the bootloader's programming services and try upload formats.

Unlocks with the known secret, then:
  - service map: sends a bare service id (incomplete, so nothing executes) and
    reads the NRC. 0x11=serviceNotSupported, 0x13=incorrectLength(=supported).
  - upload matrix: RequestUpload (0x35) for 0x100230 with several ALFIDs/sizes,
    looking for a 0x75 positive (or any NRC other than requestOutOfRange).
Writes nothing (no complete 0x34/0x36/0x2E/0x3D is ever sent).

  python flash_probe.py [COMx]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient, nrc
from seedkey_brute import wake, establish
from unlock_and_read import unlock

SERVICES = {0x34: "RequestDownload", 0x35: "RequestUpload", 0x36: "TransferData",
            0x37: "TransferExit", 0x31: "RoutineControl", 0x2E: "WriteDataByID",
            0x3D: "WriteMemByAddr", 0x23: "ReadMemByAddr", 0x22: "ReadDataByID",
            0x2C: "DynDefineDID", 0x85: "CtrlDTCSetting"}

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

    print("-- service map (bare id, incomplete => no side effects) --")
    for sid, name in SERVICES.items():
        r = c.request([sid], timeout=0.4)
        if r is None:
            tag = "(no resp)"
        elif r[0] == 0x7F:
            tag = nrc(r[2]) + (" [SUPPORTED]" if r[2] != 0x11 else " [not supported]")
        else:
            tag = "POSITIVE " + r.hex().upper()
        print(f"  {sid:02X} {name:16} -> {tag}")

    print("\n-- RequestUpload (0x35) format matrix for 0x100230 --")
    addr = 0x00100230
    tries = [
        ("ALFID14 sz28",  [0x35, 0x00, 0x14, 0x00, 0x10, 0x02, 0x30, 0x28]),
        ("ALFID24 sz0028",[0x35, 0x00, 0x24, 0x00, 0x10, 0x02, 0x30, 0x00, 0x28]),
        ("ALFID44",       [0x35, 0x00, 0x44, 0x00, 0x10, 0x02, 0x30, 0x00, 0x00, 0x00, 0x28]),
        ("dfi00 ALFID13", [0x35, 0x00, 0x13, 0x10, 0x02, 0x30, 0x28]),
        ("dfi00 ALFID12", [0x35, 0x00, 0x12, 0x02, 0x30, 0x28]),
        ("no dfi 14",     [0x35, 0x14, 0x00, 0x10, 0x02, 0x30, 0x28]),
    ]
    for name, req in tries:
        r = c.request(req, timeout=0.8)
        tag = (r.hex().upper() if r else "(no resp)")
        if r and r[0] == 0x75:
            tag = "*** POSITIVE *** " + tag
        elif r and r[0] == 0x7F:
            tag = f"NEG {nrc(r[2])} ({tag})"
        print(f"  {name:16} -> {tag}")
    c.close()

if __name__ == "__main__":
    main()
