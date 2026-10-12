#!/usr/bin/env python3
"""Actively probe the radio for diagnostic / bootloader endpoints over CAN.

  python uds_probe.py [COMx] [bitrate]

This TRANSMITS, so run it only when the adapter is wired to the radio's bus and
the radio is powered. For each candidate request ID it sends a one-frame UDS
request and listens for any reply, then prints which request ID produced a reply
from which response ID. That reveals the diagnostic address pair without having
to guess it in advance.

Requests tried per ID (each is a valid ISO-TP single frame):
  10 01   DiagnosticSessionControl (default session)   -> positive 50 01
  3E 00   TesterPresent                                 -> positive 7E 00
A negative reply (7F ..) still proves the ID is live.

Default scan: 0x700-0x7FF (Ford 11-bit diagnostic range) plus a curated list of
known Ford radio/ACM pairs. Use --full to also sweep 0x000-0x7FF (slower).
Nothing here enters programming mode; it only finds who answers.
"""
import sys, time
import serial
import can

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
BR   = int(sys.argv[2]) if len(sys.argv) > 2 else 125000
FULL = "--full" in sys.argv

CURATED = [0x7DF, 0x726, 0x727, 0x7D0, 0x730, 0x733, 0x740, 0x7E0]
REQUESTS = [bytes([0x02, 0x10, 0x01]), bytes([0x02, 0x3E, 0x00])]

def settle_open(port):
    pre = serial.Serial(port, 115200, timeout=0.3)
    time.sleep(1.5)
    pre.reset_input_buffer()
    pre.close()
    time.sleep(0.3)

def main():
    settle_open(PORT)
    bus = can.interface.Bus(interface="slcan", channel=PORT, bitrate=BR, rtscts=False)
    print(f"probing on {PORT} @ {BR} bps (TRANSMITTING)\n")

    scan = list(range(0x000, 0x800)) if FULL else sorted(set(range(0x700, 0x800)) | set(CURATED))
    found = {}          # req_id -> set of (resp_id, first_bytes)
    tx_fail = 0

    for req in scan:
        for payload in REQUESTS:
            data = payload + b"\x00" * (8 - len(payload))
            msg = can.Message(arbitration_id=req, is_extended_id=False, data=data)
            try:
                bus.send(msg, timeout=0.1)
            except can.CanError:
                tx_fail += 1
                continue
            end = time.time() + 0.08
            while time.time() < end:
                r = bus.recv(timeout=0.05)
                if r is None:
                    continue
                if r.arbitration_id == req:
                    continue                     # our own echo / same id
                key = r.arbitration_id
                found.setdefault(req, {})
                found[req][key] = bytes(r.data[:min(len(r.data), 8)])
        if req % 0x40 == 0:
            print(f"  ... scanned up to {req:03X}")

    print("\n=== responders ===")
    if not found:
        print("No replies. Either no diagnostic stack answers while LOCKED, the")
        print("wrong bitrate, or TX is not being ACKed (check wiring/termination).")
        if tx_fail:
            print(f"({tx_fail} transmits failed with no ACK - likely nothing else is")
            print(" driving the bus, or CANH/CANL / 120 ohm termination is missing.)")
    else:
        for req in sorted(found):
            for resp, d in found[req].items():
                print(f"  request {req:03X}  ->  response {resp:03X}   {d.hex(' ').upper()}")
    bus.shutdown()

if __name__ == "__main__":
    main()
