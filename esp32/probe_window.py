#!/usr/bin/env python3
"""Run the firmware 'G' window probe and print ACK/no-ACK live.

  python probe_window.py [COMx] [ratecode] [seconds]
  python probe_window.py COM10 4 35     # 125k for 35s
  python probe_window.py COM10 6 35     # 500k for 35s

ratecode is the SLCAN S-code: 3=100k 4=125k 5=250k 6=500k 8=1M.

While this runs, POWER-CYCLE THE RADIO a few times. The firmware transmits
continuously and reports "ack=N fail=N". fail climbing is normal (nobody is
acknowledging). If you ever see "ACK!" or ack climb above 0, a live CAN
controller answered in that instant - that is the bootloader window.
"""
import sys, time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"
CODE = sys.argv[2] if len(sys.argv) > 2 else "4"
DUR  = float(sys.argv[3]) if len(sys.argv) > 3 else 35.0

def main():
    s = serial.Serial(PORT, 115200, timeout=0.1)
    time.sleep(1.6)                      # board auto-resets on open; let it boot
    s.reset_input_buffer()
    s.write(("S" + CODE + "\r").encode()); time.sleep(0.2)
    s.read(s.in_waiting or 1)
    rate = {"3":"100k","4":"125k","5":"250k","6":"500k","8":"1M"}.get(CODE, CODE)
    print(f"probing at {rate} for {DUR:.0f}s - POWER-CYCLE THE RADIO NOW, a few times\n")
    s.write(b"G\r")
    t0 = time.time()
    buf = b""
    acked = False
    while time.time() - t0 < DUR:
        buf += s.read(s.in_waiting or 1)
        while b"\r" in buf:
            line, buf = buf.split(b"\r", 1)
            txt = line.decode("utf-8", "replace").strip()
            if not txt:
                continue
            print(f"  [{time.time()-t0:5.1f}s] {txt}")
            if "ACK" in txt:
                acked = True
    s.write(b"x\r")                      # any byte stops the probe
    time.sleep(0.3)
    tail = s.read(s.in_waiting or 1).decode("utf-8", "replace").strip()
    if tail:
        print("  " + tail)
    s.close()
    print()
    if acked:
        print(f"RESULT: a CAN ACK was seen at {rate} - a live controller answered. "
              "That is the window to target.")
    else:
        print(f"RESULT: no ACK at {rate}. Either the bootloader is not on these pins "
              "at this rate, or its window was missed. Try the other bitrate, or more "
              "power cycles.")

if __name__ == "__main__":
    main()
