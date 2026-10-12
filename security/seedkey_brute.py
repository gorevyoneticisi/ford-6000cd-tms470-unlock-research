#!/usr/bin/env python3
"""Brute the Ford legacy SecurityAccess keybag against the radio bootloader.

Replicates jakka351's Ford-ECU-Bruteforcer logic over our ESP32 adapter:
enter programming session (reboot to bootloader), then for each 5-byte secret
in the keybag compute the key for a fresh seed and send 27 02; stop on 67 02.

  python seedkey_brute.py [COMx] [txid_hex] [rxid_hex]

Nothing is written to flash. SecurityAccess key attempts are what the module is
designed to rate-limit; on exceedNumberOfAttempts/delay we reboot (10 02) to
reset the counter and continue. On success the secret is saved to found_secret.txt
and security is left UNLOCKED.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "esp32"))
from isotp_uds import UdsClient, nrc
from keygen_ford import key_bytes, load_keybag

HERE = os.path.dirname(os.path.abspath(__file__))

def wake(c, seconds=45):
    """Wake the radio's CAN using the firmware tight-loop probe, then UDS is ready.
    Power-cycle the radio while this runs if rapid traffic alone is not enough."""
    print("waking: firmware bus probe. If no wake in ~10s, POWER-CYCLE the radio "
          "(off ~2s, on) while this runs...")
    ok = c.s.wake_firmware(seconds=seconds)
    if ok:
        print("  radio ACKing (awake)")
    return ok

def establish(c, tries=40):
    """Send programming session and wait until the bootloader hands out seeds."""
    c.request([0x10, 0x02], timeout=1.0)
    for _ in range(tries):
        r = c.request([0x27, 0x01], timeout=0.3)
        if r and r[0] == 0x67:
            return True
        if r and r[0] == 0x7F and r[2] in (0x37, 0x36):
            time.sleep(0.5)
        time.sleep(0.05)
    return False

def get_seed(c):
    r = c.request([0x27, 0x01], timeout=0.4)
    if r and r[0] == 0x67 and len(r) >= 5:
        return (r[2] << 16) | (r[3] << 8) | r[4]
    return None, r

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    txid = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x727
    rxid = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x72F
    bag = load_keybag()
    print(f"keybag: {len(bag)} secrets. adapter {port}, {txid:03X}/{rxid:03X}\n")

    c = UdsClient(port, txid, rxid)
    if not wake(c):
        print("radio never woke. Check wiring/power and try again.")
        c.close(); return
    print("entering bootloader (10 02 reboot) ...")
    ok = False
    for attempt in range(5):
        if establish(c):
            ok = True; break
        # it may have slept during the reboot; re-wake and retry
        wake(c, seconds=20)
    if not ok:
        print("could not get seeds after reboot. retry, power-cycling if needed.")
        c.close(); return
    print("bootloader is giving seeds. starting brute.\n")

    reboots = 0
    framing_ok = None
    i = 0
    while i < len(bag):
        secret = bag[i]
        sd = get_seed(c)
        seed = sd[0] if isinstance(sd, tuple) else sd
        if seed is None:
            # no seed: radio slept or is mid-reboot. re-wake then re-enter.
            reboots += 1
            if reboots > 400:
                print("too many reboots; stopping."); break
            if not establish(c):
                wake(c, seconds=20)
                establish(c)
            continue
        key = key_bytes(seed, secret)
        resp = c.request([0x27, 0x02, key[0], key[1], key[2]], timeout=0.5)
        if resp is None:
            continue
        if resp[0] == 0x67 and resp[1] == 0x02:
            print(f"\n*** SUCCESS *** secret {secret.hex().upper()}  "
                  f"seed {seed:06X} -> key {key.hex().upper()}  (keybag index {i})")
            open(os.path.join(HERE, "found_secret.txt"), "w").write(
                f"secret={secret.hex().upper()}\nseed={seed:06X}\nkey={key.hex().upper()}\nindex={i}\n")
            print("security is now UNLOCKED. saved to found_secret.txt")
            c.close(); return
        if resp[0] == 0x7F and resp[1] == 0x27:
            code = resp[2]
            if framing_ok is None:
                framing_ok = (code == 0x35)
                print(f"first attempt NRC: {nrc(code)} -> framing "
                      f"{'OK (3-byte key accepted form)' if framing_ok else 'SUSPECT ('+nrc(code)+')'}")
                if code == 0x13:
                    print("NRC incorrectLength: key format wrong. stopping to avoid wasting attempts.")
                    c.close(); return
            if code == 0x35:                 # invalidKey -> try next secret
                i += 1
                if i % 20 == 0:
                    print(f"  tried {i}/{len(bag)} (reboots={reboots})")
                continue
            if code in (0x36, 0x37):          # exceed / delay -> reboot to reset counter
                reboots += 1
                establish(c)
                continue
            print(f"  secret {secret.hex()} -> NRC {nrc(code)}")
            i += 1
        else:
            print(f"  unexpected resp: {resp.hex()}")
            i += 1

    print(f"\nexhausted keybag ({len(bag)} secrets), no match. "
          "The module's secret is not in this keybag.")
    c.close()

if __name__ == "__main__":
    main()
