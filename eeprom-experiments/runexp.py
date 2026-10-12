import emu, time
# exp3: serve a completely blank EEPROM (all 0xFF)
for i in range(2048):
    emu.mem[i] = 0xff
emu.start()
print("EXP: BLANK image (all 0xFF)")
print("READY: power-cycle the radio now.")
tail = emu.ctl[1]
while True:
    head = emu.ctl[1]
    while tail != head:
        op = emu.logbuf[tail]
        a  = (emu.logbuf[tail + 1] << 8) | emu.logbuf[tail + 2]
        d  = emu.logbuf[tail + 3]
        if op:
            print('%s %03x %02x' % ('R' if op == 0x52 else 'W', a, d))
        tail = (tail + 4) & emu.LOGMASK
    time.sleep_ms(150)
