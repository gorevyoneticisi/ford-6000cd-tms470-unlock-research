import serial, sys, time

PORT='COM7'; baud=125000
ser=serial.Serial(PORT,921600,timeout=0.05)
time.sleep(0.3); ser.reset_input_buffer()

def setbaud(b):
    B=[(b>>24)&0xff,(b>>16)&0xff,(b>>8)&0xff,b&0xff]
    ser.write(bytes([0xAA,0x02]+B+[B[0]^B[1]^B[2]^B[3]])); time.sleep(0.3); ser.read(3000)

def wake():
    # benign confirmed frame to keep the bus (and radio) awake
    seq=1; id1=0x01; id0=0x00; x=seq^id1^id0^0x00
    ser.write(bytes([0xAA,0x09,seq,0x00,0x00,id1,id0,0x01,0x00,x]))

setbaud(baud)
print("SNIFF2 125k: logging all frames (with periodic wake). ~25s.")
sys.stdout.flush()

buf=bytearray(); t0=time.time(); last_wake=0
seen={}   # id -> last data (to show changes)
def parse():
    while buf:
        h=buf[0]
        if h==0xBB:
            if len(buf)<2: return
            ln=buf[1]; tot=7+ln
            if len(buf)<tot: return
            p=buf[:tot]; del buf[:tot]
            sid=(p[4]<<8)|p[5]; data=bytes(p[6:6+ln])
            ascii_s=''.join(chr(b) if 32<=b<127 else '.' for b in data)
            key=sid
            if seen.get(key)!=data:
                print("[%7.3f] %03X [%d] %s  |%s|"%(time.time()-t0,sid,ln,
                      ' '.join('%02X'%b for b in data),ascii_s))
                seen[key]=data
        elif h==0xBC:
            if len(buf)<2: return
            ln=buf[1]; tot=3+ln
            if len(buf)<tot: return
            del buf[:tot]
        elif h==0xBE:
            if len(buf)<4: return
            del buf[:4]
        else:
            del buf[:1]

while time.time()-t0<25:
    c=ser.read(512)
    if c:
        buf.extend(c); parse(); sys.stdout.flush()
    now=time.time()
    if now-last_wake>1.0:
        wake(); last_wake=now
ser.close()
print("done. unique IDs:", ' '.join('%03X'%k for k in sorted(seen)))
