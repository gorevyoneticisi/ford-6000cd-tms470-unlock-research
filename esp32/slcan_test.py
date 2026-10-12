#!/usr/bin/env python3
"""Quick smoke test for the esp32_slcan firmware over USB serial.

  python slcan_test.py [COMx]

Opens the port, reads the boot banner, then exercises the SLCAN command set:
V (version), N (serial), S4 (125k), O/L (open), C (close). Prints raw replies.
Does NOT require a CAN bus to be connected; it only checks the serial side.
"""
import sys, time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"

def rd(ser, t=0.6):
    time.sleep(t)
    n = ser.in_waiting
    return ser.read(n) if n else b""

def cmd(ser, c, t=0.4):
    ser.write(c.encode())
    r = rd(ser, t)
    print(f"  {c!r:14} -> {r!r}")
    return r

def main():
    print(f"opening {PORT} @115200 ...")
    ser = serial.Serial(PORT, 115200, timeout=0.3)
    # the board auto-resets on open; give it time to boot and print the banner
    time.sleep(1.5)
    banner = rd(ser, 0.5)
    print("banner:", banner)
    ser.reset_input_buffer()
    print("commands:")
    cmd(ser, "V\r")       # expect V0101
    cmd(ser, "N\r")       # expect NTMB2
    cmd(ser, "C\r")       # close (ok even if already closed)
    cmd(ser, "S4\r")      # 125k
    cmd(ser, "L\r")       # open listen-only (safe with no bus)
    time.sleep(0.3)
    extra = rd(ser, 0.5)
    if extra:
        print("listen-only rx (frames seen on bus):", extra)
    cmd(ser, "C\r")       # close
    ser.close()
    print("done")

if __name__ == "__main__":
    main()
