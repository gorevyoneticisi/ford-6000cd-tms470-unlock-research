# Ford 6000CD (Visteon, TMS470) unlock research

**Resolved.** The radio is unlocked for good, it is back in the car, and it works
flawlessly. This repo is the record of how I got there: about a month of work, three
dead ends, two bricks I had to undo myself, and an answer that was sitting in the
chip everyone dismissed in week one.

I own this radio. It came out of a 2012 Ford Galaxy Mk3 (part no. `6M2T-18C815-AG`,
board `VISTEON PWB 14041`) stuck on `LOCKED`, ignoring code entry completely. Not
"wrong code": the radio refuses entry entirely. The code itself (`9777`) was never a
mystery, it matches the serial through a calculator. The unit had simply been
power-cycled one time too many, and past that point a 6000CD stops counting attempts
and just locks you out.

Commercial tools clear this in seconds, but they are closed, priced per use, and
built on proprietary knowledge. This is a 2007-era board from a discontinued radio,
so I did it the hard way instead: public documentation, an ESP32, a Pico, an FT232H,
and a lot of logging. I did the hardware work myself. Claude (Anthropic's AI coding
agent) wrote the tooling and ran protocol analysis alongside me; this repo and
`DOCUMENTATION.md` are the working record we kept as things happened.

If your own radio is locked and you found this page: the fix that actually worked is
in section 8, and I've written it up so an owner can follow it. If you want to know
what doesn't work, that's most of this writeup, and I kept every failure in on
purpose.

## 1. The problem

A locked 6000CD gives you nothing: no code prompt, no error, just the word `LOCKED`.
The lock state has to live somewhere the front panel cannot reach, so my question
from day one was where. Three candidate locations: the processor's internal flash,
its SRAM, or the external 24C16 EEPROM.

## 2. The CAN bus and the diagnostic back door

The radio speaks UDS over CAN at 125 kbit/s and sleeps the bus within a second of
silence, which is its own little war. I built the adapter from an ESP32 and a
SN65HVD230 transceiver, and getting a stable session took a firmware-level keepalive
plus an ISO-TP/UDS client I wrote to handle `responsePending`, stale frames and
dropped requests. `esp32/` has all of it.

Once sessions were stable, two things fell out quickly:

**SecurityAccess (UDS 0x27) broke completely.** The bootloader uses Ford's legacy
24-bit LFSR scheme with a 5-byte secret. I brute-forced a public keybag of candidate
secrets against the module, there was hardly any rate limiting to speak of, and this
radio's own secret fell out of it. From then on the diagnostic session unlocked
deterministically. And here is the first big lesson of the project: it did not matter
at all. The diagnostic lock and the consumer lock are two different things. The method
is described in `DOCUMENTATION.md`; the crack tooling itself has been removed from
this repo, see the legal notes at the end.

**The bootloader accepts arbitrary writes to internal RAM.** Any address, any bytes,
over CAN, using nothing but UDS. That is a genuine code-injection foothold into a
locked automotive ECU. It is also, on this unit, unusable: I swept the entire 16-bit
RoutineControl ID space and found exactly three routines, all flash program/erase
related, none of them a way to execute what I had just loaded into RAM. I excluded
ECUReset as an execution path too, with a controlled experiment: the EEPROM
emulator's own access counter served as an independent witness that no execution
diverted. Clean, reproducible negative.

I also soldered a tap onto an undocumented debug UART pin, which I found by probing
voltages rather than reading schematics (the pin is not routed anywhere on the PCB).
It turned out to carry binary inter-module traffic, not a debug console, but the tap
and the baud-finder are in the repo and the method generalizes.

## 3. The wrong turn that cost the most time

Early on I ruled out the EEPROM. The reasoning looked solid at the time: a Pico
live-emulated the 24C16, the radio ran against a completely blank chip, and the radio
still showed `LOCKED`. Conclusion: the lock lives in the processor, the EEPROM is
just settings.

That was wrong, and the way it was wrong taught me more than the right answer would
have. A blank EEPROM does not test the lock. It tests the boot. Against an empty chip
the radio's boot degrades so badly that the lock question never even gets asked. The
lock data sat in the EEPROM the entire time, in a small block my early emulation was
not reproducing correctly. It took coming back weeks later, with a fully working
radio, full I2C control and a complete traffic capture, to finally see it. Section 8
has the details. That mistake cost me about a month.

## 4. JTAG: the part everyone said was impossible

The TMS470 family is known for its memory security module: a 128-bit password gating
flash. Earlier writeups, including my own early notes, claimed the debug port needs
TI's proprietary dual-TAP scan protocol that open tools cannot speak. For this part
that claim turned out to be wrong: an FT232H plus OpenOCD halted, resumed and read
this chip reliably for weeks. `jtag/` has the configs and the pin map.

With JTAG up, I mapped the running application in SRAM:

- module state cell `0x1035BC`: 6 = LOCKED, 2 = normal operation
- screen mode cell `0x1035C0`: 3 = the LOCKED screen, 0 = normal
- status byte `0x1038A8`, whose bit 0 arms the event that drives the LOCKED path
- service latch `0x100820`, the marker written by the diagnostic service-grant path

In flash, I located the memory security module's key rows and reproduced the unlock
ladder on real hardware. After the ladder, flash reads and writes worked and I could
dump the whole 384 KB, diff it and actually understand what was in there.

## 5. The flash month

The application-level lock turned out to be a state machine, and its constants live
in flash. So began the month of surgical patches. Each one was reasoned through,
simulated offline where possible, and reversible on paper: marker bytes in the boot
sector that the boot compares against SRAM state, an authorization word in the
identity sector, the state machine's own constants in the application sector, and
eventually a carefully designed interrupt trampoline to drive the event system from
the IRQ path, verified in an emulator for hundreds of millions of instructions before
I touched the hardware.

The result: every single boot-visible flash modification bricked the boot. Not most
of them. All of them. The boot chain on this unit reads and validates its sectors so
tightly that even a byte change in a region that looks unused broke the power-on
sequence. The trampoline, simulated clean end to end offline, broke the real boot
twice.

I recovered from those bricks the hard way. One application sector ended up partially
erased mid-session and I had to rebuild it halfword by halfword over JTAG from a
stock reference image, verifying every write before moving on. By the end my working
discipline was: dump the full 384 KB flash before and after every session, diff it
byte-exact, and revert anything that boots badly the same day. That discipline is the
only reason the radio survived this phase.

When the dust settled I had complete understanding of the lock mechanism, a volatile
unlock (next section), and a radio that boots exactly stock. The flash was a dead end
for permanence, but the reason why is documented for the next person.

## 6. The volatile unlock

With JTAG, while the radio is halted, four SRAM writes unlock it completely:

```
mww 0x100820 0x55AACC33    # service latch: the service-grant marker
mww 0x1038A8 0xCA          # status byte: clear bit 0, disarms the LOCKED event path
mww 0x1035BC 0x00000002    # module state: 6 (LOCKED) -> 2 (normal)
mww 0x1035C0 0x00000000    # screen mode: 3 (LOCKED screen) -> 0
```

Resume, and the radio is fully unlocked: normal display, responsive buttons, working
tuner. It reverts on every power cycle, because SRAM. This was never going to be the
fix. Its value was proof: I understood the lock mechanism end to end now, and the map
pointed at where permanence had to come from.

## 7. Back to the EEPROM, with eyes open

This time I went back with the radio fully working, the Pico owning the EEPROM chip
entirely, and a logger capturing every transaction. The traffic told a clear story.
On every boot the radio reads its settings sweep: presets, region data, and a small
block it reads before almost anything else. During operation it rewrites its settings
block over and over, byte for byte identical each time.

The lock lives in that small early-read block:

| Address | Meaning |
|---|---|
| `0x14C-0x14D` | accept token: `97 77` means a code was accepted for this unit |
| `0x14E-0x171` | padding and flags, all `00` in the accepted state |
| `0x172` | attempt counter: `00` means no failed attempts standing |
| `0x175` | second status byte, also `00` |
| `0x176-0x179` | lock block checksum: `00 00 00 00` validates the unlocked state |

The proof came from a snapshot I had captured weeks earlier, in the window where the
radio had actually accepted the correct code once. That image held exactly the state
above, and loading it back made the radio boot unlocked. The answer had been sitting
in my own captures the whole time.

## 8. The permanent fix

The permanent fix was three moves:

1. **The Pico becomes the EEPROM.** I pulled the physical 24C16 off the board and
   the Pico drives the same I2C bus from the radio's own 3.3V rail (VSYS to 3.3V,
   GND to GND, GP16 to SDA, GP17 to SCL). Replacing a dead EEPROM is a standard
   repair; this one just never has to end.
2. **The image is merged, not replaced.** The accepted-state lock block is combined
   with the original settings image, so the radio boots unlocked and keeps its own
   bass, treble, clock and presets. The first merge attempt showed `UNCONFIGURED` on
   boot, which taught me the checksum spans more than the lock block. The working
   merge keeps the accepted-state block intact and copies only the settings regions
   around it.
3. **The lock block becomes read-only in the emulator.** `pico-eeprom-emulator/emu.py`
   silently skips any write targeting `0x14C-0x179` while still ACKing the
   transaction, so the radio believes its writes succeeded and can never re-lock
   itself. Every other address stays writable, so settings keep saving normally while
   you use the radio. Turn it off normally after changing settings; the emulator
   flushes on bus idle.

No flash was modified. Nothing was erased. The processor cannot tell its EEPROM from
the Pico, and the lock block can no longer change.

## 9. In the car

I put the radio back into the Galaxy and it has run flawlessly since: normal display
on every boot, buttons working, tuner working, settings persisting across power
cycles. On the bench it shows `UNCONFIGURED` when booted outside the car. That is
the unit's normal bench behavior, not a fault.

## 10. What I took away from this

- Change one thing at a time. My blank-EEPROM experiment changed too much at once and
  hid the right answer for a month.
- The obvious security layer is often not the real one. Breaking UDS SecurityAccess
  completely was satisfying, and completely useless for the actual lock.
- Flash-boot coupling can be absolute. I could not change a single boot-visible flash
  byte on this unit without breaking the boot, including changes that simulated
  perfectly. Simulation covers logic, not whatever the boot actually validates.
- Live emulation beats dumps. A static dump shows bytes; a live emulator lets the
  radio's own behavior tell you which bytes matter. That is what finally cracked it.
- Log everything and revert everything. I could undo two erased sectors only because
  every session ended with a byte-exact dump and diff.

## 11. Legal and ethics

This was a repair of my own property, with the correct code known and in hand. This
writeup describes the repair path for an owner of record. Anyone without physical
access to the unit, disassembly skill and ownership gets nothing from it. Reaching
the EEPROM in the final step requires physically desoldering the radio's EEPROM and
wiring a microcontroller to its bus.

No Ford or Visteon firmware is published here. There are no flash dumps, no binaries
and no disassembly listings. I never released the processor's flash. The EEPROM
images in `eeprom-dumps/` are this radio's own configuration data, the locked
starting state, kept as evidence of where the project began. I did not publish any
unlocked EEPROM image; the text above explains how the accepted state was
reconstructed and why.

The UDS SecurityAccess crack tooling (the seed/key generator and the keybag
brute-forcer) existed in early versions of this repo and I have removed it from the
history. The algorithm it used is documented publicly elsewhere. What this repo keeps
is the finding that mattered: the diagnostic lock is not the consumer lock.

The idea that car-radio lock state can live in the EEPROM is not new. The repair
community has known it for decades, and dealers reset these units routinely from the
serial number. What I've added here is an open, reproducible method and an honest
account of every path that did not work.

## 12. What's in this repo

- `esp32/` - the DIY CAN adapter (ESP32 + SN65HVD230), the UDS client, the keepalive,
  the SCI/UART sniffer. `esp32/esp32_slcan/esp32_slcan.ino` is the firmware.
- `jtag/` - OpenOCD configs for direct JTAG access and a pin-mapped board photo.
- `pico-eeprom-emulator/` - the final unlock. `emu.py` is the 24C16 emulator with the
  read-only lock block; `main.py` handles settings flush; `orig.bin` is the locked
  starting image.
- `can/`, `captures/`, `eeprom-experiments/` - CAN tooling, protocol logs, EEPROM logs.
- `eeprom-dumps/` - this radio's own 24C16 contents, the locked state (config,
  presets, calibration, not firmware).
- `images/` - photos of the physical setup at every stage.
- `DOCUMENTATION.md` - the full dated command-by-command record. Start there for the
  detail behind every claim above.

## 13. Hardware

- Ford Galaxy Mk3 (~2012), radio Ford 6000CD by Visteon, board `VISTEON PWB 14041`
- Processor: TI `TMS470AVF689APZA` (ARM7TDMI, 384KB flash, 16KB SRAM, big-endian)
- EEPROM: 24C16 in SOT23-5, permanently replaced by a Raspberry Pi Pico

## 14. References

- Texas Instruments, *TMS470R1x Memory Security Module Reference Guide* (SPNU243):
  <https://ti.com/lit/pdf/spnu243>
- Texas Instruments, *TMS470R1VF689/688* datasheet (SPNS001). The part is long
  discontinued; search TI's literature database for the literature number.
- jakka351 - [Ford-ECU-Bruteforcer](https://github.com/jakka351/Ford-ECU-Bruteforcer),
  the public keybag used during the SecurityAccess phase (tooling removed here, the
  algorithm documentation lives there).
- fordradv3 ("VISTEON CAR RADIO TOOL"), the commercial tool whose cable-side protocol
  was partly understood by observation, see `DOCUMENTATION.md` section 6.

## License

This project's own code and writeup are released under the MIT license, see
`LICENSE`.
