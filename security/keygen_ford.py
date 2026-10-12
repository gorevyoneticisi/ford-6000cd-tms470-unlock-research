#!/usr/bin/env python3
"""Ford legacy UDS SecurityAccess seed->key (3-byte seed, 5-byte secret).

ATTRIBUTION: keygen_mk1() is a port of KeyGenMkI from jakka351's
Ford-ECU-Bruteforcer (github.com/jakka351/Ford-ECU-Bruteforcer) - credit to
jakka351 for that implementation. keygen_gist() is an independent port (the
JJTech gist) kept only for cross-checking the two agree.

load_keybag() parses jakka351's keybag format if you have a local copy of his
security.cs (see his repo above) - it's not shipped here, so get it from the
source if you need to brute-force an unknown secret; the self-check below
just skips that step if no local copy is found.

  python keygen_ford.py                      # self-check (keybag step skipped if absent)
  python keygen_ford.py <seed6hex> <secret10hex>
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))

def keygen_mk1(s: int, secret) -> int:
    """s: 24-bit seed int. secret: 5 bytes. returns 24-bit key int."""
    sknum, sknum2, sknum3, sknum4, sknum5 = secret[0], secret[1], secret[2], secret[3], secret[4]
    sknum13 = (s >> 0x10) & 0xFF
    b2 = (s >> 8) & 0xFF
    b3 = s & 0xFF
    sknum6 = (sknum13 << 0x10) + (b2 << 8) + b3
    sknum7 = ((sknum6 & 0xFF0000) >> 0x10) | (sknum6 & 0xFF00) | (sknum << 0x18) | ((sknum6 & 0xFF) << 0x10)
    sknum8 = 0xC541A9
    for i in range(0x20):
        sknum10 = ((((sknum7 >> i) & 1) ^ (sknum8 & 1)) << 0x17) | (sknum8 >> 1)
        sknum9 = sknum10
        sknum8 = ((sknum9 & 0xEF6FD7)
                  | ((((sknum9 & 0x100000) >> 0x14) ^ ((sknum10 & 0x800000) >> 0x17)) << 0x14)
                  | (((((sknum8 >> 1) & 0x8000) >> 0xF) ^ ((sknum10 & 0x800000) >> 0x17)) << 0xF)
                  | (((((sknum8 >> 1) & 0x1000) >> 0xC) ^ ((sknum10 & 0x800000) >> 0x17)) << 0xC)
                  | (0x20 * ((((sknum8 >> 1) & 0x20) >> 5) ^ ((sknum10 & 0x800000) >> 0x17)))
                  | (8 * ((((sknum8 >> 1) & 8) >> 3) ^ ((sknum10 & 0x800000) >> 0x17))))
    for j in range(0x20):
        w = (sknum5 << 0x18) | (sknum4 << 0x10) | sknum2 | (sknum3 << 8)
        sknum12 = ((((w >> j) & 1) ^ (sknum8 & 1)) << 0x17) | (sknum8 >> 1)
        sknum11 = sknum12
        sknum8 = ((sknum11 & 0xEF6FD7)
                  | ((((sknum11 & 0x100000) >> 0x14) ^ ((sknum12 & 0x800000) >> 0x17)) << 0x14)
                  | (((((sknum8 >> 1) & 0x8000) >> 0xF) ^ ((sknum12 & 0x800000) >> 0x17)) << 0xF)
                  | (((((sknum8 >> 1) & 0x1000) >> 0xC) ^ ((sknum12 & 0x800000) >> 0x17)) << 0xC)
                  | (0x20 * ((((sknum8 >> 1) & 0x20) >> 5) ^ ((sknum12 & 0x800000) >> 0x17)))
                  | (8 * ((((sknum8 >> 1) & 8) >> 3) ^ ((sknum12 & 0x800000) >> 0x17))))
    return (((sknum8 & 0xF0000) >> 0x10)
            | (0x10 * (sknum8 & 0xF))
            | ((((sknum8 & 0xF00000) >> 0x14) | ((sknum8 & 0xF000) >> 8)) << 8)
            | (((sknum8 & 0xFF0) >> 4) << 0x10))

def key_bytes(s, secret) -> bytes:
    k = keygen_mk1(s, secret)
    return bytes([(k >> 16) & 0xFF, (k >> 8) & 0xFF, k & 0xFF])

FORD_LFSR_TAPS = 0x109028
def keygen_gist(seed: bytes, fixed: bytes) -> bytes:
    f = int.from_bytes(fixed, "big")
    cc = [f & 0xFF, (f >> 8) & 0xFF, (f >> 16) & 0xFF, (f >> 24) & 0xFF, (f >> 32) & 0xFF,
          seed[2], seed[1], seed[0]]
    state = 0xC541A9
    for _ in range(64):
        bbit = (state & 1) ^ (cc[7] & 1)
        state = (state >> 1) + bbit * 0x800000
        if bbit:
            state ^= FORD_LFSR_TAPS
        cc[7] = (cc[7] >> 1) & 0xFF
        for a in range(7, 0, -1):
            cc[a] = (cc[a] + (cc[a - 1] & 1) * 128) & 0xFF
            cc[a - 1] = cc[a - 1] >> 1
    return bytes([(state >> 4) & 0xFF,
                  (((state >> 12) & 0xF) << 4) + ((state >> 20) & 0xF),
                  ((state >> 16) & 0xF) + ((state & 0xF) << 4)])

def load_keybag(path=None):
    """Parses jakka351's keybag format if you've placed a local copy of his
    security.cs (NOT included here - see the module docstring). Returns []
    with a hint printed if no file is found, rather than crashing."""
    path = path or os.path.join(HERE, "bruteforcer_security.cs")
    if not os.path.exists(path):
        print(f"(no keybag at {path} - get jakka351's security.cs from "
              f"github.com/jakka351/Ford-ECU-Bruteforcer if you need one)")
        return []
    txt = open(path, encoding="utf-8", errors="replace").read()
    bag = []
    for m in re.finditer(r"\{\s*(0x[0-9A-Fa-f]{1,2}(?:\s*,\s*0x[0-9A-Fa-f]{1,2}){4})\s*\}", txt):
        vals = [int(x, 16) for x in re.split(r"\s*,\s*", m.group(1))]
        if len(vals) == 5:
            bag.append(bytes(vals))
    # de-dup preserving order
    seen = set(); out = []
    for b in bag:
        if b not in seen:
            seen.add(b); out.append(b)
    return out

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        s = int(sys.argv[1], 16); secret = bytes.fromhex(sys.argv[2])
        print("mk1 :", key_bytes(s, secret).hex(" ").upper())
        print("gist:", keygen_gist(bytes([(s>>16)&0xFF,(s>>8)&0xFF,s&0xFF]), secret).hex(" ").upper())
    else:
        import random
        random.seed(1); agree = 0
        for _ in range(8):
            s = random.randint(0, 0xFFFFFF); secret = bytes(random.randint(0,255) for _ in range(5))
            a = key_bytes(s, secret)
            b = keygen_gist(bytes([(s>>16)&0xFF,(s>>8)&0xFF,s&0xFF]), secret)
            agree += (a == b)
            print(f"seed {s:06X} secret {secret.hex()}: mk1 {a.hex()}  gist {b.hex()}  {'OK' if a==b else 'DIFF'}")
        bag = load_keybag()
        print(f"\nmk1 vs gist agree on {agree}/8")
        print(f"keybag: {len(bag)} unique 5-byte secrets loaded")
