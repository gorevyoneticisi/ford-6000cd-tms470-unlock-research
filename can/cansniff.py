import serial, sys, time

PORT = 'COM7'
baud = int(sys.argv[1]) if len(sys.argv) > 1 else 125000

ser = serial.Serial(PORT, 921600, timeout=0.1)
time.sleep(0.3)
ser.reset_input_buffer()

def send(frame):
    ser.write(bytes(frame))

# identify adapter
send([0xAA, 0x03, 0x03])
time.sleep(0.2)

# set CAN bit rate
B = [(baud >> 24) & 0xff, (baud >> 16) & 0xff, (baud >> 8) & 0xff, baud & 0xff]
x = B[0] ^ B[1] ^ B[2] ^ B[3]
send([0xAA, 0x02] + B + [x])
print("SNIFFER: COM7, CAN set to %d bps. Power-cycle the radio now." % baud)
sys.stdout.flush()

buf = bytearray()
t0 = time.time()
frames = 0
last_status = t0

def parse():
    global frames
    while buf:
        h = buf[0]
        if h == 0xBB:                      # received CAN frame
            if len(buf) < 2: return
            ln = buf[1]
            total = 7 + ln
            if len(buf) < total: return
            pkt = buf[:total]; del buf[:total]
            id3, id2, id1, id0 = pkt[2], pkt[3], pkt[4], pkt[5]
            data = pkt[6:6+ln]; xor = pkt[6+ln]
            calc = id3 ^ id2 ^ id1 ^ id0
            for d in data: calc ^= d
            if id3 & 0x80:
                cid = ((id3 & 0x1f) << 24) | (id2 << 16) | (id1 << 8) | id0
                ids = "ext %08X" % cid
            else:
                ids = "std %03X" % ((id1 << 8) | id0)
            bad = "" if calc == xor else " !XOR"
            print("[%7.3f] RX %s [%d] %s%s" % (time.time()-t0, ids, ln,
                  ' '.join('%02X' % b for b in data), bad))
            frames += 1
        elif h == 0xBC:                    # text reply (e.g. "CAN 125000 ok")
            if len(buf) < 2: return
            ln = buf[1]; total = 3 + ln
            if len(buf) < total: return
            pkt = buf[:total]; del buf[:total]
            print("[%7.3f] MSG %r" % (time.time()-t0, bytes(pkt[2:2+ln])))
        elif h == 0xBE:                    # confirmed-TX result
            if len(buf) < 4: return
            pkt = buf[:4]; del buf[:4]
            print("[%7.3f] TXRES seq=%d st=%d" % (time.time()-t0, pkt[1], pkt[2]))
        else:
            del buf[:1]                    # resync

while True:
    chunk = ser.read(4096)
    if chunk:
        buf.extend(chunk)
        parse()
        sys.stdout.flush()
    now = time.time()
    if now - last_status > 3:
        print("[%7.3f] ... %d frames so far" % (now-t0, frames))
        sys.stdout.flush()
        last_status = now
