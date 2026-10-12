# Ford 6000CD (Visteon, TMS470) unlock research

I have a Ford 6000CD radio (Visteon, part no. `6M2T-18C815-AG`) out of a 2012 Ford Galaxy
Mk3, permanently stuck on `LOCKED`. I know the correct code (`9777`, confirmed independently
against a serial-to-code calculator, that part was never the mystery), but a 6000CD past
this point ignores code entry entirely. Getting back in means resetting an internal attempt
counter that lives inside the radio's own processor, not anywhere reachable from the front
panel.

Commercial tools clear this in seconds (OBDSTAR DC706, CarProTool, the genuine Visteon/Ford
dealer cable), but they're built around proprietary keys only the tool vendors have, and
this is a dead 2007-era chip from a long-discontinued radio, not worth paying real money to
unlock. So the goal became: see how far this gets with nothing but public documentation and
a few cheap microcontrollers.

I did the hands-on hardware work myself, soldering, wiring, running every experiment on the
actual radio. Claude (Anthropic's AI coding agent) wrote the tooling and ran the protocol
analysis alongside me. This repo and `DOCUMENTATION.md` are the record of that, kept as we
went so the work could pick back up without starting over.

## What this is

An attempt to read or reset that lock using only open tools: a DIY ESP32 CAN adapter, a
Raspberry Pi Pico acting as a fake EEPROM, an FT232H for JTAG, and a logic
analyzer/multimeter for probing the board directly. No commercial diagnostic tool was used
against the radio itself. `DOCUMENTATION.md` section 6 covers what I learned about how the
commercial Visteon radio tool ("fordradv3") talks to the radio, from watching it run, not
from copying its code.

## What I've actually got working

This went further than "it's still locked" suggests.

I built a CAN/UDS adapter from an ESP32 and a two-dollar transceiver, no existing adapter,
no vendor tooling, and used it to find and talk to the radio's diagnostic endpoint over its
CAN bus. Then I broke the radio's SecurityAccess scheme (UDS 0x27) outright: identified
Ford's legacy 24-bit LFSR algorithm, found the specific 5-byte secret this radio uses by
trying a public keybag of candidates against it, and now the bootloader's security layer
unlocks deterministically, every time.

Getting a stable diagnostic session took its own work, this radio sleeps its CAN bus within
about a second of silence, so I built a firmware-level keepalive and an ISO-TP/UDS client
that handles responsePending, stale frames, and dropped requests, to hold the connection
open indefinitely. With that in place, I confirmed the radio boots into its Primary Boot
Loader on command, and mapped every UDS service it exposes there.

The biggest find: the bootloader will accept arbitrary bytes written to any address in the
processor's internal RAM over CAN. That's a real code-injection foothold into a locked
automotive ECU, reached with nothing but UDS requests. I then mapped what that foothold
*can't* do just as thoroughly, not as a guess: swept the entire 16-bit RoutineControl ID
space, all of it, and found exactly three routines, all flash program/erase related, none
of them a way to run the code sitting in RAM. Tested ECUReset too, as a different possible
execution path, with an actual controlled experiment behind it (a second, independent
channel, an EEPROM emulator's own access counter, to detect whether execution diverted).
Clean, reproducible negative: ECUReset doesn't trigger it either.

On the JTAG side, I reached the TAP directly over an FT232H and got a reliable chip ID read
(`0x3100e02f`), proving JTAG is physically alive on the board. I also ran down why it can't
go further: this TI chip family uses a proprietary dual-TAP debug-scan protocol that
open-source JTAG tooling doesn't implement, confirmed against TI's own support forum
threads on sibling chips, not just assumed from the symptoms.

I soldered a tap onto an undocumented debug UART pin on the board, found by testing pin
voltages directly rather than from any datasheet (the pin isn't even routed anywhere on the
PCB), and built a baud-finder and sniffer for it. Turned out to carry binary inter-module
traffic rather than a debug console, but the tap and the method of finding it are real,
reusable results regardless.

And I properly ruled out the EEPROM as the lock's location: live-emulated the radio's
external 24C16 from a Raspberry Pi Pico, so its contents could be edited while the radio
ran against it rather than just read once, and a completely blank EEPROM still left the
radio showing LOCKED. The lock lives inside the processor's own flash, not the chip most
guides assume.

Every claim above is backed by command-by-command logs and working scripts in this repo,
see `DOCUMENTATION.md` for the dated, detailed record behind each one.

## Where I'm actually stuck

The TMS470 (TI ARM7TDMI, 384KB flash) has a hardware security module gating its flash
behind a 128-bit password that isn't recoverable by analysis, it's not derivable from
anything public, and brute-forcing 128 bits isn't realistic the way the 40-bit UDS secret
was. I tried two independent doors into that flash, and both are shut for confirmed,
specific reasons, not abandoned early:

- **Over CAN**, the bootloader runs a handful of specific flash routines (needed for
  official reflashing) but has no general "execute arbitrary code" entry point, confirmed
  by exhausting the entire RoutineControl ID space.
- **Over JTAG**, the debug port needs TI's own proprietary scan protocol that no open tool
  speaks, so halting the core (required to read anything) isn't possible with generic
  hardware.

One lead I haven't tried yet: a forum report of someone getting an actual flash readback on
this exact chip using genuine SEGGER J-Link hardware and a specific J-Flash project setting
("Activate mapping"), see `DOCUMENTATION.md` section 5.11. I don't have real J-Link hardware
to try it with.

## If you know something about this

If you've worked with TMS470/TMS470R1 debug internals, have the real Ford/Visteon Secondary
Bootloader (SBL) for this module (part no. `6M2T-18C815-AG` / `6M2T-14C230-AF`), have a
genuine J-Link and want to try the lead above, or just want to poke at a RAM-write primitive
on a real automotive ECU, open an issue, or fork it and run with it. Everything needed to
reproduce every step here is in this repo.

## What's in this repo

- `esp32/` - the DIY CAN adapter (ESP32 + SN65HVD230) built from scratch to talk UDS to the
  radio, plus a passive SCI/UART sniffer added later. `esp32/esp32_slcan/esp32_slcan.ino`
  is the firmware.
- `security/` - the SecurityAccess crack and every bootloader/RAM-exploit probe tried
  (RequestDownload/Upload, the full RoutineControl ID sweep, the controlled ECUReset
  experiment, etc).
- `jtag/` - OpenOCD configs for direct JTAG access and a pin-mapped photo of the board.
- `pico-eeprom-emulator/` - a Raspberry Pi Pico W used as a live 24C16 EEPROM emulator, to
  read/write/log the radio's EEPROM traffic without desoldering the original chip.
- `can/`, `captures/`, `eeprom-experiments/` - earlier-stage CAN tooling and EEPROM logs.
- `eeprom-dumps/` - this specific radio's own 24C16 contents (not firmware, just config/
  presets/calibration bytes).
- `images/` - photos of the physical setup at various stages: the CH341A/SOIC8 EEPROM
  reader, the Pico soldered in as a live EEPROM emulator (with the TMS470 chip visible on
  the board), the two Visteon boards connected together, the JTAG test points wired up, the
  FT232H JTAG adapter, and the full bench with everything connected at once.
- `DOCUMENTATION.md` - the full, dated, command-by-command technical record. Start there
  for the real detail behind every claim above.

## Hardware

- Ford Galaxy Mk3 (~2012), radio Ford 6000CD by Visteon, board `VISTEON PWB 14041`.
- Processor: TI `TMS470AVF689APZA` (ARM7TDMI, 384KB flash, 16KB SRAM, big-endian).
- EEPROM: 24C16 in SOT23-5.

## References

- Texas Instruments, *TMS470R1x Memory Security Module Reference Guide* (literature no.
  SPNU243): <https://ti.com/lit/pdf/spnu243>
- Texas Instruments, *TMS470R1VF689, TMS470R1VF688 16/32-Bit RISC Flash Microcontrollers*
  datasheet (literature no. SPNS001) - TI's own listing for this specific part has since
  been taken down (it's long discontinued); search TI's literature database for "SPNS001"
  or the part number.
- jakka351 - [profile](https://github.com/jakka351) /
  [Ford-ECU-Bruteforcer](https://github.com/jakka351/Ford-ECU-Bruteforcer): source of the
  Ford legacy SecurityAccess seed/key algorithm this project's `keygen_ford.py` ports, and
  of the candidate-secret keybag used to find this radio's specific secret.
- fordradv3 ("VISTEON CAR RADIO TOOL") - the commercial Ford/Visteon radio-code tool this
  project's CAN/UDS protocol was partly understood by observing.

## License

This project's own code and writeup are released under the MIT license (see `LICENSE`),
except where a file says otherwise (the Ford seed/key algorithm port, see the credit in
`security/keygen_ford.py` and the References section above).
