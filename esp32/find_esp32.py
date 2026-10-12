#!/usr/bin/env python3
"""Find/await the ESP32 serial port and confirm esptool can talk to it.

Default: WATCH mode - snapshots current ports, then waits for a newly plugged
device (skipping the Raspberry Pi Pico), and probes it with esptool.

  python find_esp32.py                 # watch for a new device, then probe
  python find_esp32.py --list          # list ports once and exit
  python find_esp32.py --port COMx     # probe a specific port
"""
import sys, time, subprocess
import serial.tools.list_ports

ESP_CHIP_VIDS = {
    0x10C4: "Silabs CP210x",
    0x1A86: "WCH CH340/CH9102",
    0x303A: "Espressif native USB",
    0x0403: "FTDI",
    0x1B4F: "SparkFun",
}
KNOWN_NOT_ESP = {0x2E8A: "Raspberry Pi Pico"}   # always skipped

def comports():
    return list(serial.tools.list_ports.comports())

def describe(p):
    vid = p.vid or 0; pid = p.pid or 0
    tag = KNOWN_NOT_ESP.get(vid) or ESP_CHIP_VIDS.get(vid, "")
    return f"{p.device:8}  VID:PID={vid:04X}:{pid:04X}  {p.description}  {tag}".rstrip()

def list_once():
    print("=== serial ports ===")
    for p in comports():
        print(describe(p))

def probe(port):
    print(f"\n==> probing {port} with esptool (pulses DTR/RTS to enter the bootloader)...")
    r = subprocess.run([sys.executable, "-m", "esptool", "--port", port, "chip-id"])
    return r.returncode == 0

def watch(timeout=0):
    base = {p.device for p in comports()}
    print("current ports (baseline, will be skipped):")
    for p in comports():
        print("   " + describe(p))
    print("\nWaiting for a NEW device to be plugged in (ESP32). The Pico is skipped.")
    print("Swap to a DATA USB cable + a direct PC port if nothing appears. Ctrl-C to stop.\n")
    start = time.time(); beat = 0
    while True:
        for p in comports():
            if p.device in base:
                continue
            vid = p.vid or 0
            if vid in KNOWN_NOT_ESP:
                base.add(p.device); continue       # ignore a freshly plugged Pico
            print("NEW DEVICE: " + describe(p))
            if probe(p.device):
                print("\nRESULT: ESP32 ready and in bootloader on " + p.device)
                return p.device
            print("  (no esptool response on that port; still watching)\n")
            base.add(p.device)
        if timeout and (time.time() - start) > timeout:
            print("timeout: no new device appeared"); return None
        beat += 1
        if beat % 10 == 0:
            print(f"  ...still waiting ({int(time.time()-start)}s)")
        time.sleep(1)

def main():
    a = sys.argv[1:]
    if "--list" in a:
        list_once(); return
    if "--port" in a:
        port = a[a.index("--port") + 1]
        print("RESULT:", ("ESP32 ready on " + port) if probe(port) else ("no response on " + port))
        return
    watch(timeout=0)

if __name__ == "__main__":
    main()
