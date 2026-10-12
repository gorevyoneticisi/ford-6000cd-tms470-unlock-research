#!/usr/bin/env python3
"""Find the SCI baud by capturing at several rates and scoring readable content.

Hold the probe steady on the test point and power-cycle the radio a few times
during the run. For each baud it prints: bytes captured, % printable, and the
number of letter-runs (>=3 consecutive A-Za-z) - the real baud should have the
most word-like content and show actual words.

  python sci_baudfind.py COM10
"""
import sys, time, re
import serial

BAUDS = [9600, 19200, 38400, 57600, 76800, 115200, 4800, 31250, 62500]

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    ser = serial.Serial(port, 115200, timeout=0.1)
    time.sleep(0.3); ser.reset_input_buffer()
    print("Hold contact; power-cycle the radio a few times during the run.\n")
    def score(src, baud, raw):
        n=len(raw); pr=sum(1 for x in raw if 32<=x<127)/n*100 if n else 0
        words=re.findall(rb'[A-Za-z]{3,}', bytes(raw))
        sample=b" ".join(words[:8]).decode('latin-1','replace')
        print(f"  @{src} GPIO{34 if src=='1' else 35}: {n:5d} B  printable {pr:4.0f}%  "
              f"letter-runs {len(words):3d}  {sample[:50]}")
        return len(words)
    best=(0,None,None)
    for baud in BAUDS:
        ser.reset_input_buffer(); ser.write(f"U{baud}\r".encode())
        raw={'1':bytearray(),'2':bytearray()}
        t=time.time()+7; buf=b""
        while time.time()<t:
            chunk=ser.read(512)
            if not chunk: continue
            buf+=chunk
            while b"\r" in buf:
                line,buf=buf.split(b"\r",1)
                m=re.search(r'@([12])([0-9A-Fa-f]+)', line.decode("latin-1","replace"))
                if m:
                    h=m.group(2)
                    for i in range(0,len(h)-1,2):
                        try: raw[m.group(1)].append(int(h[i:i+2],16))
                        except: pass
        print(f"===== {baud} baud =====")
        for src in '12':
            w=score(src,baud,raw[src])
            if w>best[0]: best=(w,baud,src)
    ser.write(b"U0\r"); ser.close()
    print(f"\nmost word-like: @{best[2]} at {best[1]} baud ({best[0]} letter-runs)" if best[1] else "\nno text found")

if __name__ == "__main__":
    main()
