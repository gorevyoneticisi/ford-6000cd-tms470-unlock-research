# 24C16 I2C EEPROM emulator for RP2040 / MicroPython (Pico W)
# SDA = GP16, SCL = GP17  (open-drain: drive low or release, external pull-ups on the bus)
# Core1 runs a viper bit-FSM; core0 keeps the USB REPL for live control + logging.
#
# No clock stretching in v1: viper is fast enough to respond within a bit at <=100 kHz.
# Validate with the CH341 (read it as a 24C16 in AsProgrammer) before touching the radio.

import machine, _thread, array, uctypes

SDA = 16
SCL = 17

# --- EEPROM image ---
def _loadimg(fn='eeprom.bin'):
    m = bytearray(2048)
    try:
        b = open(fn, 'rb').read()
        for i in range(min(2048, len(b))):
            m[i] = b[i]
    except Exception as e:
        print('no image:', e)
    return m

mem    = _loadimg()
orig   = bytes(mem)

# log ring: 4096 entries x 4 bytes = 16384 (mask 0x3fff). entry = op,'addrhi','addrlo','data'
LOGMASK = 0x3fff
logbuf  = bytearray(16384)

# ctl[0]=run 1]=loghead 2]=reads 3]=writes 4]=starts 5]=wordptr 6]=stops
ctl = array.array('i', [0, 0, 0, 0, 0, 0, 0, 0])

# configure pins as SIO inputs, OUT latch low so enabling OE drives low
_p_sda = machine.Pin(SDA, machine.Pin.IN)
_p_scl = machine.Pin(SCL, machine.Pin.IN)
machine.mem32[0xd0000010] &= ~((1 << SDA) | (1 << SCL))   # GPIO_OUT clear these bits

_mem_a = uctypes.addressof(mem)
_log_a = uctypes.addressof(logbuf)
_ctl_a = uctypes.addressof(ctl)


@micropython.viper
def _run(mem_p: ptr8, log_p: ptr8, ctl_p: ptr32):
    IN     = ptr32(0xd0000004)
    OE_SET = ptr32(0xd0000024)
    OE_CLR = ptr32(0xd0000028)
    sda_m = 1 << 16
    scl_m = 1 << 17

    prev_scl = 1
    prev_sda = 1
    st = 0            # 0 idle, 1 addr, 2 waddr, 3 wdata, 4 read
    bitcnt = 0
    shift = 0
    acking = 0
    rphase = 0        # read: 0 sending data bits, 1 waiting master ack
    block = 0
    word = int(ctl_p[5]) & 0xff
    outbyte = 0
    outbit = 0
    loghead = int(ctl_p[1]) & 0x3fff

    OE_CLR[0] = sda_m | scl_m   # release both

    while int(ctl_p[0]) != 0:
        v = int(IN[0])
        scl = v & scl_m
        sda = v & sda_m

        # START / STOP: SDA edge while SCL high
        if scl != 0:
            if prev_scl != 0:
                if prev_sda != 0:
                    if sda == 0:
                        st = 1; bitcnt = 0; shift = 0; acking = 0; rphase = 0
                        ctl_p[4] = int(ctl_p[4]) + 1
                else:
                    if sda != 0:
                        st = 0; acking = 0; rphase = 0
                        OE_CLR[0] = sda_m
                        ctl_p[6] = int(ctl_p[6]) + 1

        # SCL rising edge
        if scl != 0:
            if prev_scl == 0:
                if acking == 0:
                    if st == 1 or st == 2 or st == 3:
                        shift = (shift << 1) | (1 if sda != 0 else 0)
                        bitcnt += 1
                    elif st == 4:
                        if rphase == 1:
                            if sda != 0:
                                st = 0          # NACK -> transfer done
                            # ACK: continue, load handled on next falling

        # SCL falling edge
        if scl == 0:
            if prev_scl != 0:
                if acking != 0:
                    OE_CLR[0] = sda_m           # release our ACK
                    acking = 0
                    if st == 4:
                        # begin sending: load current byte, drive bit7
                        addr = (block << 8) | word
                        outbyte = int(mem_p[addr])
                        lh = loghead
                        log_p[lh] = 0x52
                        log_p[lh + 1] = addr >> 8
                        log_p[lh + 2] = addr & 0xff
                        log_p[lh + 3] = outbyte
                        loghead = (lh + 4) & 0x3fff
                        ctl_p[1] = loghead
                        ctl_p[2] = int(ctl_p[2]) + 1
                        word = (word + 1) & 0xff
                        outbit = 7
                        if (outbyte >> 7) & 1:
                            OE_CLR[0] = sda_m
                        else:
                            OE_SET[0] = sda_m
                        rphase = 0
                elif st == 1:
                    if bitcnt == 8:
                        rw = shift & 1
                        a7 = shift >> 1
                        if (a7 & 0x78) == 0x50:
                            block = a7 & 7
                            OE_SET[0] = sda_m    # ACK
                            acking = 1
                            if rw != 0:
                                st = 4
                            else:
                                st = 2
                        else:
                            st = 0
                        bitcnt = 0; shift = 0
                elif st == 2:
                    if bitcnt == 8:
                        word = shift & 0xff
                        OE_SET[0] = sda_m        # ACK
                        acking = 1
                        st = 3
                        bitcnt = 0; shift = 0
                elif st == 3:
                    if bitcnt == 8:
                        addr = (block << 8) | word
                        mem_p[addr] = shift & 0xff
                        lh = loghead
                        log_p[lh] = 0x57
                        log_p[lh + 1] = addr >> 8
                        log_p[lh + 2] = addr & 0xff
                        log_p[lh + 3] = shift & 0xff
                        loghead = (lh + 4) & 0x3fff
                        ctl_p[1] = loghead
                        ctl_p[3] = int(ctl_p[3]) + 1
                        word = (word + 1) & 0xff
                        OE_SET[0] = sda_m        # ACK
                        acking = 1
                        bitcnt = 0; shift = 0
                elif st == 4:
                    if rphase == 0:
                        if outbit > 0:
                            outbit -= 1
                            if (outbyte >> outbit) & 1:
                                OE_CLR[0] = sda_m
                            else:
                                OE_SET[0] = sda_m
                        else:
                            OE_CLR[0] = sda_m    # release for master ACK/NACK
                            rphase = 1
                    else:
                        # master ACK consumed on rising; load next byte now
                        addr = (block << 8) | word
                        outbyte = int(mem_p[addr])
                        lh = loghead
                        log_p[lh] = 0x52
                        log_p[lh + 1] = addr >> 8
                        log_p[lh + 2] = addr & 0xff
                        log_p[lh + 3] = outbyte
                        loghead = (lh + 4) & 0x3fff
                        ctl_p[1] = loghead
                        ctl_p[2] = int(ctl_p[2]) + 1
                        word = (word + 1) & 0xff
                        outbit = 7
                        if (outbyte >> 7) & 1:
                            OE_CLR[0] = sda_m
                        else:
                            OE_SET[0] = sda_m
                        rphase = 0

        prev_scl = scl
        prev_sda = sda

    ctl_p[1] = loghead
    ctl_p[5] = word
    OE_CLR[0] = sda_m | scl_m


# ---------------- core0 control API ----------------
def start():
    if ctl[0]:
        print('already running'); return
    ctl[0] = 1
    _thread.start_new_thread(_run, (_mem_a, _log_a, _ctl_a))
    print('i2c emulator running on GP%d(SDA)/GP%d(SCL)' % (SDA, SCL))

def stop():
    ctl[0] = 0
    print('stopped')

def stats():
    print('run=%d starts=%d stops=%d reads=%d writes=%d wordptr=%d' %
          (ctl[0], ctl[4], ctl[6], ctl[2], ctl[3], ctl[5]))

def getlog(n=40):
    head = ctl[1]
    n = min(n, 4096)
    for i in range(n):
        p = (head - (n - i) * 4) & LOGMASK
        op = logbuf[p]
        if op == 0:
            continue
        a = (logbuf[p + 1] << 8) | logbuf[p + 2]
        d = logbuf[p + 3]
        print('%s 0x%03x = %02x' % ('R' if op == 0x52 else 'W', a, d))

def dump(a=0x140, n=0x40):
    for off in range(a, a + n, 16):
        row = ' '.join('%02x' % mem[off + i] for i in range(16) if off + i < 2048)
        print('%03x: %s' % (off, row))

def setb(a, v):
    mem[a] = v & 0xff
    print('set 0x%03x = %02x' % (a, v & 0xff))

def reset():
    for i in range(2048):
        mem[i] = orig[i]
    print('image reset to original')

def save(fn='eeprom_mod.bin'):
    open(fn, 'wb').write(mem)
    print('saved', fn)

print('emu loaded. start() to run. SDA=GP16 SCL=GP17. GND common with master.')
