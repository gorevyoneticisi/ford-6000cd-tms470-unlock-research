#!/usr/bin/env python3
"""ECUReset-diverts-to-RAM test, verified via the Pico 24C16 emulator's live read
counter (independent of the flaky SCI wire). The Pico (COM16) already logs every
I2C read the radio's firmware makes to EEPROM. Normal firmware reads EEPROM at
various points including boot; our RAM infinite-loop stub never touches I2C at
all. So: if the chip boots flash normally after ECUReset, the Pico's read counter
resumes incrementing within a bounded time. If the chip is stuck in our stub, the
counter stays completely flat until the AWD watchdog (if it ever catches a loop
with no WD-key service) reboots it, or until a manual power-cycle.

Does NOT touch/reset the Pico (uses the same gentle plain-serial REPL as
picorepl.py, never mpremote, so the running emulator + its log survive).

  python ecureset_pico_test.py [COMx_radio] [COMx_pico]
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
import serial
from isotp_uds import UdsClient
from seedkey_brute import wake, establish
from unlock_and_read import unlock

RAM = 0x00400000
LOOP_STUB = bytes([0xEA, 0xFF, 0xFF, 0xFE])   # B . (infinite loop)

def hx(r): return r.hex(' ').upper() if r else "(no response)"

def download(c, addr, data):
    sz = len(data)
    r = c.request([0x34,0x00,0x44,(addr>>24)&0xFF,(addr>>16)&0xFF,(addr>>8)&0xFF,addr&0xFF,
                   (sz>>24)&0xFF,(sz>>16)&0xFF,(sz>>8)&0xFF,sz&0xFF], timeout=1.0)
    if not r or r[0]!=0x74: return False, r
    tr = c.request([0x36,0x01]+list(data), timeout=1.5)
    if not tr or tr[0]!=0x76: return False, tr
    ex = c.request([0x37], timeout=1.0)
    return (bool(ex and ex[0]==0x77)), ex

class Pico:
    """Minimal gentle REPL talker (same method as picorepl.py): plain serial open,
    text + CR only, NEVER Ctrl-C/Ctrl-D, so the running emulator thread + its
    read/write log are never disturbed."""
    def __init__(self, port="COM16"):
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.ser.write(b"\r"); time.sleep(0.15); self.ser.read(self.ser.in_waiting or 1)
        self._send("import emu")

    def _send(self, line, wait=0.25):
        self.ser.write((line + "\r").encode())
        time.sleep(wait)
        return self.ser.read(self.ser.in_waiting or 1).decode("utf-8", "replace")

    def reads(self):
        out = self._send("emu.stats()")
        for tok in out.split():
            if tok.startswith("reads="):
                return int(tok.split("=")[1])
        return None

    def close(self):
        self.ser.close()

def main():
    args = [a for a in sys.argv[1:] if a != "control"]
    control = "control" in sys.argv[1:]   # control run: skip the stub, just reset (establishes
                                           # the NORMAL recovery timing to compare the real test against)
    radio_port = args[0] if len(args) > 0 else "COM10"
    pico_port  = args[1] if len(args) > 1 else "COM16"
    if control:
        print("*** CONTROL RUN: no stub will be loaded, this just measures normal reset timing ***\n")

    pico = Pico(pico_port)
    base_reads = pico.reads()
    print(f"Pico baseline EEPROM reads counter: {base_reads}")
    if base_reads is None:
        print("could not read Pico stats; check COM16 / that emu is running. Stopping.")
        pico.close(); return

    c = UdsClient(radio_port, 0x727, 0x72F)
    if not wake(c): print("no wake; power-cycle during probe."); c.close(); pico.close(); return
    if not establish(c): wake(c,20); establish(c)
    ok, info = unlock(c)
    if not ok: print(f"unlock FAILED: {info}"); c.close(); pico.close(); return
    print(f"radio UNLOCKED (seed {info[0]:06X})\n")

    if control:
        print("== CONTROL: skipping stub load ==")
    else:
        print(f"== loading infinite-loop stub at RAM 0x{RAM:08X} ==")
        okd, dr = download(c, RAM, LOOP_STUB)
        print(f"  stub load: {'OK' if okd else 'FAILED '+hx(dr)}")
        if not okd: c.close(); pico.close(); return

    print("\n== firing ECUReset 0x11 01 ==")
    t_fire = time.time()
    r = c.request([0x11, 0x01], timeout=1.5)
    print(f"  response -> {hx(r)}  (t+{time.time()-t_fire:.2f}s)")

    print("\n== polling Pico read-counter every ~1s for 20s (t=0 is the reset) ==")
    first_increment_at = None
    last = base_reads
    end = time.time() + 20
    while time.time() < end:
        now = time.time() - t_fire
        n = pico.reads()
        delta = (n - base_reads) if n is not None else None
        marker = ""
        if n is not None and n != last:
            if first_increment_at is None:
                first_increment_at = now
                marker = "  <<< FIRST NEW READ since the reset"
            last = n
        print(f"  t+{now:5.2f}s  reads={n}  (+{delta})" + marker)
        time.sleep(1.0)

    print("\n== trying to re-establish CAN session ==")
    recovered = wake(c, 10)
    print(f"  CAN recovered: {recovered}")
    c.close(); pico.close()

    print("\n=== VERDICT ===")
    if first_increment_at is None:
        print("NO new EEPROM reads in 20s after the reset. The firmware never resumed its normal")
        print("boot-time EEPROM access pattern. This is CONSISTENT WITH THE STUB HAVING RUN and the")
        print("CPU being stuck in the infinite loop (EEPROM reads only resume once real firmware runs).")
        print("If CAN also did not recover above, power-cycle the radio now to clear RAM and recover.")
    elif first_increment_at < 2.0:
        print(f"EEPROM reads resumed almost immediately (t+{first_increment_at:.2f}s). This is CONSISTENT")
        print("WITH A NORMAL RESET straight back to flash - the stub most likely never executed, or if")
        print("it did, something returned/recovered from it essentially instantly.")
    else:
        print(f"EEPROM reads resumed, but only after a {first_increment_at:.2f}s delay. This is AMBIGUOUS:")
        print("could be a normal but slow boot sequence, OR the stub ran and a watchdog reset recovered")
        print("it within that window. Not conclusive either way without a known-good baseline timing.")

if __name__ == "__main__":
    main()
