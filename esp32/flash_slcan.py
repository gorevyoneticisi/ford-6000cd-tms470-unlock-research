#!/usr/bin/env python3
"""Compile (optional) and flash the esp32_slcan firmware to the ESP32.

  python flash_slcan.py              # flash the already-built merged.bin
  python flash_slcan.py --build      # recompile first, then flash
  python flash_slcan.py --port COM10 # pick the port

IMPORTANT - this board's auto-program circuit does NOT pull GPIO0 low on its own,
so esptool cannot enter the download mode by itself. You must hold BOOT by hand:

  1. Start this script.
  2. The moment you see "Connecting...." dots, PRESS AND HOLD the BOOT button.
  3. Keep holding through ALL the dots, until you see "Writing at 0x...".
  4. Release BOOT.

If it prints "Wrong boot mode detected (0x13)", BOOT was not held during the
reset - just run it again and hold BOOT sooner / longer.
"""
import os, sys, subprocess

HERE   = os.path.dirname(os.path.abspath(__file__))
SKETCH = os.path.join(HERE, "esp32_slcan")
BUILD  = os.path.join(HERE, "build")
MERGED = os.path.join(BUILD, "esp32_slcan.ino.merged.bin")
CLI    = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
FQBN   = "esp32:esp32:esp32"

def build():
    print("compiling ...")
    r = subprocess.run([CLI, "compile", "--fqbn", FQBN, "--output-dir", BUILD, SKETCH])
    if r.returncode != 0:
        sys.exit("compile failed")

def flash(port):
    if not os.path.exists(MERGED):
        sys.exit(f"no firmware at {MERGED} - run with --build first")
    print("\n>>> HOLD THE BOOT BUTTON as soon as you see 'Connecting....' and keep")
    print(">>> holding until 'Writing at 0x...' appears, then release.\n")
    cmd = [sys.executable, "-m", "esptool", "--port", port,
           "--before", "default-reset", "--after", "hard-reset",
           "--connect-attempts", "10", "write-flash", "0x0", MERGED]
    subprocess.run(cmd)

def main():
    a = sys.argv[1:]
    port = "COM10"
    if "--port" in a:
        port = a[a.index("--port") + 1]
    if "--build" in a:
        build()
    flash(port)

if __name__ == "__main__":
    main()
