#!/usr/bin/env python3
"""Gently drive the Pico's MicroPython REPL over plain pyserial.

Unlike mpremote (which sends Ctrl-C/Ctrl-D and soft-resets the board on every
connect, wiping the running emulator thread and its read-log), a plain serial
open does NOT reset an RP2040 running MicroPython. This tool only sends printable
command text + CR, so the emulator keeps running and its log survives.

  python picorepl.py start      # import emu; emu.start()   (begin serving)
  python picorepl.py stats      # emu.stats()               (run/reads/writes)
  python picorepl.py log [n]    # emu.getlog(n)             (last n R/W accesses)
  python picorepl.py raw "expr" # send an arbitrary REPL line

NEVER sends 0x03 (Ctrl-C) or 0x04 (Ctrl-D), so it cannot interrupt or reset.
"""
import sys, time
import serial

PORT = "COM16"

def talk(lines, settle=0.4, per=0.6):
    ser = serial.Serial(PORT, 115200, timeout=0.1)
    time.sleep(settle)
    ser.reset_input_buffer()
    out = bytearray()
    ser.write(b"\r")                      # nudge a fresh prompt
    time.sleep(0.2); out += ser.read(ser.in_waiting or 1)
    for ln in lines:
        ser.write((ln + "\r").encode())
        time.sleep(per)
        out += ser.read(ser.in_waiting or 1)
    ser.close()
    return out.decode("utf-8", "replace")

def main():
    a = sys.argv[1:]
    cmd = a[0] if a else "stats"
    if cmd == "start":
        lines = ["import emu", "emu.start()", "emu.stats()"]
    elif cmd == "stats":
        lines = ["import emu", "emu.stats()"]
    elif cmd == "log":
        n = a[1] if len(a) > 1 else "60"
        lines = ["import emu", f"emu.getlog({n})"]
    elif cmd == "raw":
        lines = [a[1]]
    else:
        print(__doc__); return
    print(talk(lines))

if __name__ == "__main__":
    main()
