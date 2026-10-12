import emu, time
emu.start()
print("READY: emulator live. Power on the radio now.")
tail = emu.ctl[1]
n = 0
while True:
    head = emu.ctl[1]
    while tail != head:
        op = emu.logbuf[tail]
        a  = (emu.logbuf[tail+1] << 8) | emu.logbuf[tail+2]
        d  = emu.logbuf[tail+3]
        if op:
            print('%s %03x %02x' % ('R' if op == 0x52 else 'W', a, d))
            n += 1
        tail = (tail + 4) & emu.LOGMASK
    time.sleep_ms(150)
