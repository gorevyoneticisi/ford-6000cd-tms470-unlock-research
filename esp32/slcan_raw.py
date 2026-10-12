#!/usr/bin/env python3
"""Minimal raw SLCAN client for the esp32_slcan firmware.

Why not just use python-can's slcan backend? Because that backend always opens
the channel in NORMAL mode ('O'), which makes the ESP32 ACK every frame on the
bus. For first-contact sniffing of the Ford radio we want LISTEN-ONLY ('L') so
the adapter is electrically passive and cannot disturb or wake anything. This
client drives the firmware directly and supports both modes.

Bitrate codes: 10k=S0 20k=S1 50k=S2 100k=S3 125k=S4 250k=S5 500k=S6 800k=S7 1M=S8
"""
import time
import serial

# Windows' default timer resolution is ~15.6 ms, which makes short sleeps and
# serial read timeouts coarse and jittery. Request 1 ms resolution so ISO-TP
# pacing and polling are tight. Harmless no-op off Windows.
import sys as _sys
if _sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

RATE_CODE = {10000:0, 20000:1, 50000:2, 100000:3, 125000:4,
             250000:5, 500000:6, 800000:7, 1000000:8}

class Frame:
    __slots__ = ("id", "ext", "rtr", "data", "t")
    def __init__(self, ident, ext, rtr, data, t):
        self.id, self.ext, self.rtr, self.data, self.t = ident, ext, rtr, data, t
    def __repr__(self):
        w = 8 if self.ext else 3
        d = self.data.hex(" ").upper()
        return f"{self.id:0{w}X} [{len(self.data)}] {d}" + ("  RTR" if self.rtr else "")

class Slcan:
    def __init__(self, port, bitrate=125000, listen_only=True, settle=1.6):
        if bitrate not in RATE_CODE:
            raise ValueError(f"unsupported bitrate {bitrate}; use one of {sorted(RATE_CODE)}")
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        # the board auto-resets when the port opens; let it boot before commands
        time.sleep(settle)
        self.ser.reset_input_buffer()
        self._cmd("C")                       # ensure closed
        self._cmd(f"S{RATE_CODE[bitrate]}")  # set bitrate
        self._cmd("L" if listen_only else "O")
        if not listen_only:
            self._cmd("K1")                  # firmware keepalive: hold the radio awake
        self.buf = bytearray()

    def _cmd(self, s, wait=0.15):
        self.ser.write((s + "\r").encode())
        time.sleep(wait)

    def status(self):
        """Read and clear the SLCAN status byte (0x08=overrun, 0x20=bus error, 0x80=bus-off)."""
        self.ser.reset_input_buffer()
        self.ser.write(b"F\r")
        time.sleep(0.1)
        r = self.ser.read(self.ser.in_waiting or 1)
        i = r.find(b"F")
        if i >= 0 and len(r) >= i + 3:
            try:
                return int(r[i+1:i+3], 16)
            except ValueError:
                return None
        return None

    def poll(self):
        """Return a list of Frame received since the last poll."""
        n = self.ser.in_waiting
        if n:
            self.buf += self.ser.read(n)
        out = []
        while True:
            i = self.buf.find(b"\r")
            if i < 0:
                break
            line = bytes(self.buf[:i]); del self.buf[:i+1]
            f = self._parse(line)
            if f:
                out.append(f)
        return out

    @staticmethod
    def _parse(line):
        if not line:
            return None
        c = chr(line[0])
        if c not in "tTrR":
            return None
        ext = c in "TR"; rtr = c in "rR"
        idlen = 8 if ext else 3
        try:
            ident = int(line[1:1+idlen], 16)
            dlc = int(chr(line[1+idlen]), 16)
        except (ValueError, IndexError):
            return None
        data = b""
        if not rtr:
            hexs = line[2+idlen:2+idlen+dlc*2]
            try:
                data = bytes.fromhex(hexs.decode())
            except ValueError:
                return None
        return Frame(ident, ext, rtr, data, time.time())

    def wake_firmware(self, seconds=45, hold_after_ack=0.6):
        """Use the firmware 'G' probe (tight continuous-TX loop) to wake the radio's
        CAN, then reopen the normal channel for UDS, all on the same connection so
        there is no port-reopen gap for the radio to sleep in. Returns True if the
        radio started ACKing. Power-cycle the radio while this runs if needed."""
        ser = self.ser
        self._cmd("C")
        ser.reset_input_buffer()
        ser.write(b"G\r")
        t0 = time.time(); buf = b""; awake = False
        while time.time() - t0 < seconds:
            buf += ser.read(ser.in_waiting or 1)
            if b"ACK!" in buf:
                awake = True
                time.sleep(hold_after_ack)   # let it settle in the awake state
                break
            time.sleep(0.02)
        ser.write(b"x\r")                    # stop G
        time.sleep(0.08)
        ser.read(ser.in_waiting or 1)        # drain G's final line
        # reopen the normal channel quickly for UDS (minimise the silent gap) and
        # turn on the firmware keepalive so the radio does not drift back to sleep
        ser.write(b"S4\rO\rK1\r")
        time.sleep(0.05)
        self.buf = bytearray()
        ser.reset_input_buffer()
        return awake

    def send(self, ident, data=b"", ext=False, rtr=False):
        c = ("T" if ext else "t")
        if rtr:
            c = ("R" if ext else "r")
        w = 8 if ext else 3
        s = f"{c}{ident:0{w}X}{len(data):X}" + data.hex().upper()
        self._cmd(s, wait=0.0)

    def close(self):
        try:
            self._cmd("C")
            self.ser.close()
        except Exception:
            pass
