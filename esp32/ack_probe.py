#!/usr/bin/env python3
"""Decide whether a live CAN node is on the bus, by ACK, at each bitrate.

  python ack_probe.py [COMx]

At the CAN protocol level, every powered controller on the bus ACKs any valid
frame sent at the matching bitrate, even if its application never replies. So we
send a few frames in NORMAL mode and read the adapter's error status:

  status 0x00 after TX  -> frames were ACKed -> a live node is present at this rate
  status 0x20 / 0x80    -> bus error / bus-off -> nobody ACKed (wrong rate or no node)

This transmits, so it needs the adapter wired to the radio and the radio powered.
It sends only to ID 0x7FF with zero data, which any ECU ignores.
"""
import sys, time
from slcan_raw import Slcan

PORT  = sys.argv[1] if len(sys.argv) > 1 else "COM10"
RATES = [125000, 250000, 500000, 1000000, 100000]

def test(br):
    s = Slcan(PORT, bitrate=br, listen_only=False)
    s.status()                       # clear flags
    for _ in range(8):
        s.send(0x7FF, b"\x00")
        time.sleep(0.03)
    time.sleep(0.2)
    st = s.status()
    s.close()
    time.sleep(0.4)
    return st

def main():
    print(f"port {PORT}, transmitting test frames (ID 7FF)\n")
    acked = []
    for br in RATES:
        st = test(br)
        flag = ""
        if st is None:
            verdict = "no status"
        elif st == 0:
            verdict = "ACKed -> LIVE NODE at this bitrate"
            acked.append(br)
        else:
            if st & 0x20: flag += " BUS_ERROR"
            if st & 0x80: flag += " BUS_OFF"
            if st & 0x08: flag += " OVERRUN"
            verdict = "no ACK" + flag
        print(f"{br:>8} bps: status=0x{(st or 0):02X}  {verdict}")
    print()
    if acked:
        print(f"RESULT: a live CAN node ACKs us at {acked} - physical link and bitrate OK.")
        print("Next: active probing (uds_probe.py) at that rate.")
    else:
        print("RESULT: nothing ACKed at any rate. Either our SN65HVD230 TX/RX path")
        print("is not working (power / Rs pin / CTX-CRX wiring), or the radio's CAN")
        print("controller is not active on these pins. A loopback self-test ('Y')")
        print("would isolate which side.")

if __name__ == "__main__":
    main()
