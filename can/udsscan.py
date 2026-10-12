import serial, time

PORT='COM7'; baud=125000
ser=serial.Serial(PORT,921600,timeout=0.02)
time.sleep(0.3); ser.reset_input_buffer()

def setbaud(b):
    B=[(b>>24)&0xff,(b>>16)&0xff,(b>>8)&0xff,b&0xff]
    ser.write(bytes([0xAA,0x02]+B+[B[0]^B[1]^B[2]^B[3]])); time.sleep(0.3); ser.read(3000)

def tx(canid, data, seq=1):
    id1=(canid>>8)&0xff; id0=canid&0xff; ln=len(data)
    x=seq^0^0^id1^id0
    for d in data: x^=d
    ser.write(bytes([0xAA,0x09,seq,0x00,0x00,id1,id0,ln]+list(data)+[x]))

def rx(window=0.02):
    out=[]; t0=time.time(); buf=bytearray()
    while time.time()-t0<window:
        c=ser.read(128)
        if c: buf.extend(c)
    i=0
    while i<len(buf):
        h=buf[i]
        if h==0xBB and i+2<=len(buf) and i+7+buf[i+1]<=len(buf):
            ln=buf[i+1]; sid=(buf[i+4]<<8)|buf[i+5]; d=bytes(buf[i+6:i+6+ln])
            out.append((sid,d)); i+=7+ln
        elif h==0xBE and i+4<=len(buf): i+=4
        elif h==0xBC and i+2<=len(buf) and i+3+buf[i+1]<=len(buf): i+=3+buf[i+1]
        else: i+=1
    return out

setbaud(baud)
print("UDS scan 0x700-0x7FF: DiagnosticSessionControl(extended)")
# drain the broadcast noise first
rx(0.3)
NOISE={0x50C,0x1E9,0x2D5,0x2D8,0x2D9,0x2DA,0x2DB,0x2DC,0x2E3,0x4D0}
hits=0
for rid in range(0x700,0x800):
    tx(rid,[0x02,0x10,0x03,0x00,0x00,0x00,0x00,0x00])
    for sid,d in rx(0.015):
        if sid in NOISE: continue
        # UDS positive to 0x10 = 0x50; negative = 0x7F
        if len(d)>=2 and (d[1]==0x50 or d[1]==0x7F or (len(d)>=3 and d[1] in (0x50,0x7F))):
            print("  REQ %03X -> RESP %03X: %s"%(rid,sid,' '.join('%02X'%b for b in d))); hits+=1
        else:
            print("  REQ %03X -> %03X: %s"%(rid,sid,' '.join('%02X'%b for b in d))); hits+=1
print("scan done, hits=%d"%hits)

# also try functional broadcast 0x7DF
print("functional 0x7DF session control:")
tx(0x7DF,[0x02,0x10,0x03,0,0,0,0,0])
for sid,d in rx(0.3):
    if sid not in NOISE:
        print("  %03X: %s"%(sid,' '.join('%02X'%b for b in d)))
ser.close(); print("end")
