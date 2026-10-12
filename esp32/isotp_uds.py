#!/usr/bin/env python3
"""Minimal ISO-TP / UDS client over the esp32_slcan adapter (slcan_raw transport).

Talks only to one diagnostic pair (default 0x727 request / 0x72F response), so it
does NOT broadcast to the bus. Handles single-frame requests and single- or
multi-frame responses (sends a flow-control frame and collects consecutive
frames). Continuous request traffic keeps the radio's CAN awake.

Used as a library (UdsClient) and as a script that runs a read-only probe:
  python isotp_uds.py [COMx] [txid_hex] [rxid_hex]
  python isotp_uds.py COM10 727 72F
"""
import sys, time
from slcan_raw import Slcan

class UdsClient:
    def __init__(self, port, txid=0x727, rxid=0x72F, bitrate=125000):
        self.txid, self.rxid = txid, rxid
        self.s = Slcan(port, bitrate=bitrate, listen_only=False)
        time.sleep(0.2)
        self.s.poll()

    def _send_frame(self, data8):
        self.s.send(self.txid, bytes(data8))

    def _rx_frames(self):
        return [f for f in self.s.poll() if f.id == self.rxid]

    def _send_multiframe(self, req, timeout=1.0):
        """Send a request >7 bytes as ISO-TP FF + CF, honouring the ECU flow control."""
        total = len(req)
        ff = bytes([0x10 | ((total >> 8) & 0x0F), total & 0xFF]) + bytes(req[:6])
        self._send_frame(ff + b"\x00" * (8 - len(ff)))
        # wait for a flow-control frame
        end = time.time() + timeout
        bs, stmin = 0, 0
        while time.time() < end:
            for f in self._rx_frames():
                if f.data and (f.data[0] >> 4) == 3:
                    bs = f.data[1] if len(f.data) > 1 else 0
                    stmin = f.data[2] if len(f.data) > 2 else 0
                    break
            else:
                time.sleep(0.002); continue
            break
        idx = 6; seq = 1
        st = (stmin / 1000.0) if stmin <= 0x7F else 0.0001
        while idx < total:
            chunk = req[idx:idx + 7]
            cf = bytes([0x20 | (seq & 0x0F)]) + bytes(chunk)
            self._send_frame(cf + b"\x00" * (8 - len(cf)))
            idx += 7; seq += 1
            if st:
                time.sleep(st)

    def request(self, req, timeout=1.5):
        """Send a UDS request and return the assembled response bytes (SF or multi-frame).

        Robust against: multi-frame responses (sends flow control), responsePending
        (0x78, keeps waiting), and stale/late responses for other services (ignored
        by matching the service id). Returns None on timeout."""
        svc = req[0]
        # drain any stale rx before we send
        for _ in range(3):
            self.s.poll(); time.sleep(0.001)
        if len(req) <= 7:
            sf = bytes([len(req)]) + bytes(req)
            self._send_frame(sf + b"\x00" * (8 - len(sf)))
        else:
            self._send_multiframe(req)

        end = time.time() + timeout
        assembled = None
        remaining = 0
        while time.time() < end:
            for f in self._rx_frames():
                d = f.data
                if not d:
                    continue
                pci = d[0] >> 4
                msg = None
                if pci == 0:                       # single frame
                    msg = bytes(d[1:1 + (d[0] & 0x0F)])
                elif pci == 1:                     # first frame
                    total = ((d[0] & 0x0F) << 8) | d[1]
                    assembled = bytearray(d[2:8])
                    remaining = total - len(assembled)
                    # flow control: CTS, no block limit, STmin 5ms so the radio does
                    # not outrun the 115200 serial on consecutive frames
                    self._send_frame(bytes([0x30, 0x00, 0x05, 0, 0, 0, 0, 0]))
                    if remaining <= 0:
                        msg = bytes(assembled[:total]); assembled = None
                elif pci == 2 and assembled is not None:   # consecutive frame
                    take = min(7, remaining)
                    assembled += d[1:1 + take]
                    remaining -= take
                    if remaining <= 0:
                        msg = bytes(assembled); assembled = None
                if msg is None:
                    continue
                # validate the completed message against the service we asked for
                if msg and msg[0] == (svc + 0x40):
                    return msg                               # positive response
                if len(msg) >= 3 and msg[0] == 0x7F and msg[1] == svc:
                    if msg[2] == 0x78:                       # responsePending: wait more
                        end = time.time() + timeout
                        continue
                    return msg                               # our negative response
                # otherwise it's a stale/other-service frame: ignore and keep waiting
            time.sleep(0.002)
        return None

    def close(self):
        self.s.close()

def nrc(code):
    m = {0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
         0x13: "incorrectLength", 0x22: "conditionsNotCorrect",
         0x31: "requestOutOfRange", 0x33: "securityAccessDenied",
         0x35: "invalidKey", 0x36: "exceedNumberOfAttempts",
         0x7E: "subFunctionNotSupportedInSession", 0x7F: "serviceNotSupportedInSession"}
    return m.get(code, f"0x{code:02X}")

def show(label, resp):
    if resp is None:
        print(f"  {label:30} -> (no response)")
    elif len(resp) >= 3 and resp[0] == 0x7F:
        print(f"  {label:30} -> NEG 7F {resp[1]:02X} {nrc(resp[2])}")
    else:
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in resp)
        print(f"  {label:30} -> {resp.hex(' ').upper()}   |{txt}|")

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    txid = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x727
    rxid = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x72F
    c = UdsClient(port, txid, rxid)
    print(f"UDS on tx {txid:03X} / rx {rxid:03X} (read-only probe)\n")
    show("DiagSession default (10 01)", c.request([0x10, 0x01]))
    show("TesterPresent (3E 00)",       c.request([0x3E, 0x00]))
    show("ReadDID VIN (22 F1 90)",      c.request([0x22, 0xF1, 0x90]))
    show("ReadDID serial (22 F1 8C)",   c.request([0x22, 0xF1, 0x8C]))
    show("ReadDID spare (22 F1 11)",    c.request([0x22, 0xF1, 0x11]))
    show("ReadDID appl sw (22 F1 95)",  c.request([0x22, 0xF1, 0x95]))
    show("ReadDID ecu name (22 F1 97)", c.request([0x22, 0xF1, 0x97]))
    show("Extended session (10 03)",    c.request([0x10, 0x03]))
    show("Programming session (10 02)", c.request([0x10, 0x02]))
    c.close()

if __name__ == "__main__":
    main()
