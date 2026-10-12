import emu, time
emu.start()
print("MONITOR: emulating 24C16 on GP16(SDA)/GP17(SCL). Waiting for master...")
last = 0
idle = 0
while True:
    h = emu.ctl[1]
    if h != last:
        emu.getlog(16)
        emu.stats()
        last = h
        idle = 0
    else:
        idle += 1
        if idle % 5 == 0:
            emu.stats()
    time.sleep_ms(1000)
