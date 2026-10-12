#!/usr/bin/env python3
"""Capture the radio's SCI/UART output via the ESP32 passive sniffer.

The updated esp32_slcan firmware taps the TMS470 SCI TX lines on input-only pins
(GPIO34 = chip SCI1TX/pin31 -> "@1", GPIO35 = chip SCI2TX/pin34 -> "@2") and
streams the bytes. This tool drives that:

  python sci_monitor.py COM10 measure [1|2]   # auto-detect baud (power-cycle radio during the 5s window)
  python sci_monitor.py COM10 monitor <baud>  # live decode @1/@2 to ASCII (Ctrl-C to stop)
  python sci_monitor.py COM10 raw             # dump everything the firmware prints

Workflow: 'measure' first (power-cycle the radio so any boot banner drives the
line); if it reports a baud, run 'monitor <baud>' and power-cycle again to read
the text. If 'measure' sees no activity on either pin, the firmware simply isn't
printing to SCI (debug off) and this avenue is dry.
"""
import sys, time
import serial

def decode_at(line):
    # line like "@1" + hexpairs
    src = line[1:2]
    hx = line[2:]
    try:
        data = bytes.fromhex(hx)
    except ValueError:
        return None
    txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"[SCI{src}] {data.hex(' ').upper()}  |{txt}|"

def main():
    if len(sys.argv) < 3:
        print(__doc__); return
    port = sys.argv[1]; mode = sys.argv[2].lower()
    ser = serial.Serial(port, 115200, timeout=0.1)
    time.sleep(0.3)
    ser.reset_input_buffer()

    if mode == "sweep":
        bauds = sys.argv[3].split(",") if len(sys.argv) > 3 else \
            ["9600","19200","38400","57600","115200","4800","10400","28800","76800"]
        print("baud sweep: hold the probe steady (and power-cycle the radio a couple of times). "
              "Each baud is tried ~5s; readable ASCII = the right one.")
        for b in bauds:
            ser.reset_input_buffer()
            ser.write(f"U{b}\r".encode())
            print(f"\n===== trying {b} baud =====")
            t = time.time() + 5
            buf = b""
            while time.time() < t:
                chunk = ser.read(256)
                if not chunk:
                    continue
                buf += chunk
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    s = line.decode("latin-1", "replace").strip("\n")
                    if s.startswith("@") and len(s) >= 2 and s[1] in "12":
                        out = decode_at(s)
                        if out:
                            print(out)
        ser.write(b"U0\r")
        ser.close()
        return

    if mode == "measure":
        pin = sys.argv[3] if len(sys.argv) > 3 else "1"
        ser.write(f"B{pin}\r".encode())
        print(f"measuring baud on SCI{pin} (GPIO{'34' if pin=='1' else '35'}). "
              f"POWER-CYCLE the radio now (off ~2s, on)...")
        deadline = time.time() + 8
    elif mode == "monitor":
        if len(sys.argv) < 4: print("need baud"); return
        baud = sys.argv[3]
        ser.write(f"U{baud}\r".encode())
        print(f"monitoring SCI at {baud} 8N1. Power-cycle the radio / trigger 10 02 to see output. Ctrl-C to stop.")
        deadline = None
    elif mode == "raw":
        deadline = None
    else:
        print("unknown mode"); return

    buf = b""
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    s = line.decode("latin-1", "replace").strip("\n")
                    if not s:
                        continue
                    if s.startswith("@") and len(s) >= 2 and s[1] in "12":
                        out = decode_at(s)
                        if out:
                            print(time.strftime("%H:%M:%S"), out)
                    else:
                        print(time.strftime("%H:%M:%S"), s)
            if deadline and time.time() > deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if mode == "monitor":
            ser.write(b"U0\r")
        ser.close()

if __name__ == "__main__":
    main()
