import serial, time

PORT = 'COM7'
ser = serial.Serial(PORT, 921600, timeout=0.2)
time.sleep(0.3); ser.reset_input_buffer()

def setbaud(baud):
    B = [(baud>>24)&0xff,(baud>>16)&0xff,(baud>>8)&0xff,baud&0xff]
    ser.write(bytes([0xAA,0x02]+B+[B[0]^B[1]^B[2]^B[3]]))
    time.sleep(0.3); ser.read(2000)

def confirmed_tx(canid, data, seq=1):
    id3,id2,id1,id0 = 0,0,(canid>>8)&0xff,canid&0xff
    ln=len(data); x=seq^id3^id2^id1^id0
    for d in data: x^=d
    ser.write(bytes([0xAA,0x09,seq,id3,id2,id1,id0,ln]+list(data)+[x]))

STAT={0:'TRANSMITTED (ACKed - a node is on the bus!)',1:'QUEUE_FULL',
      2:'NOT_ACKED (nothing ACKed - wrong pins/baud or radio CAN asleep)',
      3:'BUS_ERROR (electrical: wiring/termination/levels)',4:'CANCELLED'}

def drain_and_report(secs=1.5):
    t0=time.time(); buf=bytearray()
    while time.time()-t0<secs:
        c=ser.read(256)
        if c: buf.extend(c)
    i=0
    while i<len(buf):
        h=buf[i]
        if h==0xBE and i+4<=len(buf):
            print('   TXRES status=%d: %s'%(buf[i+2],STAT.get(buf[i+2],'?'))); i+=4
        elif h==0xBB and i+2<=len(buf) and i+7+buf[i+1]<=len(buf):
            ln=buf[i+1]; sid=(buf[i+4]<<8)|buf[i+5]; d=buf[i+6:i+6+ln]
            print('   RX std %03X [%d] %s'%(sid,ln,' '.join('%02X'%b for b in d))); i+=7+ln
        elif h==0xBC and i+2<=len(buf) and i+3+buf[i+1]<=len(buf):
            ln=buf[i+1]; print('   MSG %r'%bytes(buf[i+2:i+2+ln])); i+=3+ln
        else: i+=1

for baud in (500000,125000):
    print('=== CAN %d bps ==='%baud)
    setbaud(baud)
    print(' sending test frame to 0x7E0 (Tester Present)...')
    confirmed_tx(0x7E0,[0x02,0x3E,0x00,0x00,0x00,0x00,0x00,0x00])
    drain_and_report(1.5)
    print(' sending test frame to 0x100...')
    confirmed_tx(0x100,[0x00],seq=2)
    drain_and_report(1.0)
ser.close()
print('done')
