#!/usr/bin/env python3
"""Confirm python-can's slcan backend can drive the esp32_slcan adapter.

  python pycan_test.py [COMx] [bitrate]

No CAN bus is required. This only checks that the backend opens the channel,
that the firmware accepts the open/bitrate commands, and that a receive call
returns cleanly (None on timeout when nothing is on the bus). It does NOT try to
transmit, because with no other node a transmit would go unacknowledged.
"""
import sys, time
import serial
import can

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
BR   = int(sys.argv[2]) if len(sys.argv) > 2 else 125000

def main():
    # The board auto-resets when the port is first opened. Open once ourselves,
    # let it boot, then hand a settled port to python-can.
    pre = serial.Serial(PORT, 115200, timeout=0.3)
    time.sleep(1.5)
    pre.reset_input_buffer()
    pre.close()
    time.sleep(0.3)

    print(f"opening python-can slcan on {PORT} @ {BR} ...")
    bus = can.interface.Bus(interface="slcan", channel=PORT, bitrate=BR,
                            rtscts=False)
    print("bus open:", bus.channel_info)
    print("listening 2s (no frames expected on an idle/unconnected bus) ...")
    end = time.time() + 2.0
    seen = 0
    while time.time() < end:
        m = bus.recv(timeout=0.3)
        if m is not None:
            seen += 1
            print("  RX", m)
    print(f"frames seen: {seen}")
    bus.shutdown()
    print("python-can slcan backend OK")

if __name__ == "__main__":
    main()
