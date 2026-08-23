# SNC7320 boot and KB7 recovery model

Review date: 2026-08-23
Source: Sonix *SNC7320 Series Data Sheet*, revision 2.1, 1 June 2022
Source SHA-256: `d360aca16c2695f12edf91d263b2994b36edf5ad6faf130547a9220dfaca94b4`

## Outcome

Directly programming the KB7's external SPI NOR remains the strongest recovery
route because it does not require working custom firmware. The SNC73200 M1
variant contains 8 MiB of volatile SiP OPI PSRAM, not persistent firmware flash;
the SoC boots from a separate storage device (Data Sheet pp. 10, 38 and 83).

A CH341B PCB has now read the in-circuit external flash twice through flashrom.
Both complete 32-MiB reads are bit-identical. JEDEC ID `c2 20 19` identifies a
Macronix `MX25L25635F/MX25L25645G`; status `0x00` showed block protection, WEL
and WIP clear. The board was later measured at approximately 5 V on CS and is
not safe for further direct use with this 3.3-V flash without level translation.

An ESP32-C3 SPI repair subsequently restored normal stock boot. Boot was
unreliable while the unpowered programmer remained connected and recovered when
it was physically disconnected. The owner subsequently confirmed a complete
full-chip SPI restore/verification rehearsal, and two later full-chip USB reads
of the restored image were byte-identical. External SPI is therefore the
demonstrated rollback path for this development unit.

On 2026-08-23 the preserved V1.22 flash loader also completed one guarded
512-byte marker program and normal-NOR erase cycle at offset `0x0008e000`. Both
32-MiB postflight images matched their exact expectations and the final image
returned byte-for-byte to the baseline. This validates one narrow command
sequence, not a supported USB flasher or recovery substitute.

A later read-only audit recovered the stock application's deliberate return to
that preserved loader. V1.22, V1.24 and V1.33 all write the same mailbox
marker, copy an identical 88-byte routine to SRAM, copy the preserved loader
from flash XIP into PRAM, and only then issue AIRCR `SYSRESETREQ`. The exact
stock software path is therefore statically proved. The independently authored
replacement-firmware proof passes offline and defaults off, but it has not run
on hardware; it does not yet prove that custom code reaches `10f5:5037`. See
[`STOCK-LOADER-REENTRY-2026-08-23.md`](STOCK-LOADER-REENTRY-2026-08-23.md).

The fixed install/restore campaign for that proof now passes offline simulation
and fault testing. Its stable target is the checksum-valid proof Core 0 plus
exact stock Core 1; one temporary Core-1 sector checksum poison protects the
Core-0 rebuild and is restored before final commit. Two exact owner baselines
now reproduce the reviewed 168-operation campaign ID and both stable images.
The separate executor pins that identity but remains independently live-locked.
See the
[`fixed proof campaign`](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md).

The board pad labeled `MCU_RST` is a strong candidate for active-low `RSTN`,
which is package lead 88 on the presumed SNC73200 LQFP128. It measured about
3.2 V released and 0.2 V when grounded through 1 kΩ during the successful reads.
Continuity to lead 88 must still be measured with power removed (pp. 11 and 21).

This document is a recovery design and validation checklist, not permission to
flash the current prototype.

## Boot and reset state model

```mermaid
flowchart TD
    A["POR, external RSTN, LVR/LVD, DPD wake, or WDT reset"] --> B["Core 0 mask ROM"]
    B --> C["Scan supported boot devices for identifying mark"]
    C -->|"no mark"| D["USB-ISP mode"]
    C -->|"valid source"| E["Parse load table and copy user code to PRAM at address 0"]
    E --> F["Software reset into current PRAM image"]
    F --> G["Execute application PRAM vector"]
    G -->|"bare AIRCR SYSRESETREQ"| F
    G -->|"marker + copy preserved loader from XIP while executing in SRAM"| H["PRAM now contains preserved loader"]
    H -->|"AIRCR SYSRESETREQ"| I["Loader consumes marker and enters 10f5:5037"]
    G -. "Core 0-controlled, details unpublished" .-> J["Core 1 / shared I-cache execution"]
```

The ROM scan and load-table path are documented on p. 44. Reset destinations
are documented on p. 43. The search order, identifying bytes, load-table
format, USB identity/protocol, second-core release fields, and failure behavior
for a partly corrupt valid container are not published.

The key correction is the PRAM loop: an ARM AIRCR software reset restarts PRAM,
not mask ROM. A mailbox flag plus `SYSRESETREQ` alone therefore cannot be called
loader entry. The later stock audit supplies the missing operation: stock runs
from SRAM while replacing the complete 64-KiB PRAM window with
`0x60001000..0x60011000`, then resets. The copied loader consumes, clears and
reads back the marker before selecting its updater entry. Ordinary public builds
still use marker-and-park; the equivalent relocation is behind a separate,
default-off hardware-validation gate.

## Recovery layers

| Layer | What the datasheet establishes | KB7 status |
|---|---|---|
| External SPI-NOR programmer | External XIP window, SFC controller, 1/2/4-bit reads, 1/4-bit writes, and common command families (pp. 37–39) | Two identical original reads, a successful ESP32-C3 full-stock restore/verification rehearsal and normal boot; demonstrated rollback route for the development unit |
| External `RSTN` | Release restarts through ROM; SNC73200 lead 88 (pp. 21 and 43) | `MCU_RST` voltage behavior, repeated read isolation and a full restore are demonstrated; direct continuity/waveform are optional documentation |
| ROM USB-ISP | ROM enters it when no boot identifying mark is found (p. 44) | Identity/protocol and behavior with a corrupt-but-present identifying mark remain unknown |
| Preserved flash loader | Recovered loader is separate from mask ROM | Observed over USB as `10f5:5037`; exact full-chip reads, a marker cycle, and a guarded exact-footprint cycle at one target passed. It remains an experimental path, not a supported flasher or recovery substitute |
| Stock preserved-loader re-entry | Not specified by the datasheet; compatible with its PRAM-reset rule | Hash-pinned instruction semantics prove the complete marker/SRAM-copy/PRAM-copy/reset/consumer route in V1.22, V1.24 and V1.33. The clean-room custom proof and fixed install/restore campaign pass offline; live commit defaults off and the proof remains hardware-unrun |
| SWD | One SWD port; SNC73200 SWO/SWCLK/SWDIO are leads 11/12/13 (pp. 1, 11 and 19) | Connect-under-reset and core visibility are untested; no erase operation is authorized |
| Watchdog reset | Underflow can reset through ROM; WDT uses the 32-kHz ILRC (pp. 43 and 57–58) | Stock proves two instances and feed/disable/reset-trigger writes despite the omitted register table; mailbox retention and a complete custom policy remain unvalidated secondary options |
| Software reset | Restarts PRAM (p. 43) | Not loader entry by itself; it completes the stock route only after the preserved loader has replaced PRAM |

## External flash and reset pins

The default SFC-capable group for SNC73200 is (pp. 20, 22, 24 and 27–28):

| Signal | SoC pad | Package lead |
|---|---|---:|
| chip select | P0.8 | 110 |
| clock | P0.9 | 42 |
| MISO / IO1 | P0.10 | 119 |
| MOSI / IO0 | P0.11 | 39 |
| IO2 / write protect | P0.12 | 121 |
| IO3 | P0.13 | 44 |

These are SoC capabilities, not proof of KB7 PCB continuity. P0.12 is also the
recovered touch interrupt. Before quad-SPI is assumed, determine whether the
flash uses only a single/dual data path or whether board-level isolation or
time multiplexing exists.

## Safe validation order

### With power removed

1. Photograph the complete SoC and flash markings, pin-1 indicators, board
   revision, and both PCB sides.
2. Optionally document continuity from `MCU_RST` to SNC lead 88; identify a
   known ground before any external connection.
3. Map all flash pins to the SoC-capable SFC leads and record series resistors,
   buffers, level shifters, test pads, and other bus masters.
4. Check resistance from the flash supply to the board's candidate 3.3-V and
   1.8-V rails; do not infer voltage from package style.
5. Prefer nearby passives/test pads over probing the 0.4-mm-pitch SoC leads.

### Under current-limited stock power

1. Measure the SoC I/O, core, and OPI rails. Nominal values are 3.30 V, 1.22 V,
   and 1.82 V (p. 79).
2. Measure `MCU_RST` released voltage and observe whether grounding it asserts
   reset without excessive current. A temporary series resistor is safer than
   an unexplained hard short until the reset circuit is traced.
3. Assert reset before applying USB power. Verify with an oscilloscope or logic
   analyzer that SFC chip select, clock, and data lines are inactive before
   attaching a programmer.
4. If USB powers the board, disconnect the programmer's target-VCC output.
   Connect only common ground and voltage-compatible logic signals. Do not let
   two supplies drive the same rail.
5. Do not power only the flash on an otherwise unpowered board unless its rail
   and signal paths are isolated; protection structures can back-power the SoC.
6. Disconnect an ESP32 or other programmer completely before boot unless its
   unpowered pins are proven high-impedance; the KB7 failed to boot reliably
   while an unpowered ESP32-C3 remained attached to the SFC lines.

The power-up requirement is that VDDC be above 1.2 V for the run transition and
VDDIO33 exceed 1.8 V before RSTN reaches 1.8 V (p. 81). Holding reset low while
board rails rise is consistent with that requirement, but it does not validate
the KB7's regulator or supervisor circuitry.

### Programmer and restore proof

Steps 1–4 below have now been substantially completed for the 32-MiB main array;
the canonical evidence is in `FULL-FLASH-ACQUISITION-2026-08-22.md`. Flashrom
warns that the chip's OTP area is not included in a normal read. Step 5 remains
the policy for any future non-test write.

1. Read and record JEDEC ID, status/configuration registers, block protection,
   quad-enable state, and 3-byte/4-byte address mode.
2. Read the complete chip at least twice without writing and require identical
   cryptographic hashes.
3. Store two independent raw backups plus metadata. A full recovery image must
   retain the identifying mark, load table, loader, application regions,
   configuration/calibration, vendor assets, and erased padding—not merely the
   extracted PRAM/I-cache payloads.
4. Demonstrate a complete restore and byte-for-byte verification/readback on a
   spare or otherwise safely recoverable setup before any custom image
   experiment. This has been completed on the development unit.
5. Use bounded sector-aware read-modify-write operations; never use whole-chip
   erase for initial work.

## What can still defeat direct recovery

Direct programming bypasses broken PRAM code, USB, clocks, display, and the
software reset path. It does not solve:

- the wrong programmer voltage or unsupported flash command/address mode;
- bus contention because reset did not actually isolate the SoC;
- another powered device sharing the flash bus;
- rail back-powering or ground/reference mistakes;
- a physically damaged or locked flash chip;
- a bad backup or incomplete boot container; or
- releasing reset into an image whose early execution damages hardware.

The successful ESP32-C3 full-chip restore/verification rehearsal is a real
recovery result. A release-quality runbook should retain the exact tooling,
wiring, reset isolation, hashes and disconnect-before-boot procedure, and it
must be rehearsed again if any of those conditions change.

## Missing information to collect

- complete SoC and flash markings and clear PCB photographs;
- optional direct `MCU_RST`-to-lead-88 continuity and reset waveform records;
- exact flash rail, configuration/security/OTP state, 4-byte address behavior,
  and SFC wiring width;
- preservation of the demonstrated full-stock restore procedure and exact
  post-restore hashes in owner-controlled records;
- passive SFC capture during stock boot and update;
- SWD accessibility/core routing under reset;
- mask-ROM USB-ISP identity and protocol; the exercised preserved-loader subset
  is recorded separately;
- optional watchdog/remap register semantics from `SNC7320_reg_vx.xx` if a
  secondary recovery design is pursued; and
- one bounded hardware run of the default-off custom re-entry proof, requiring
  `10f5:5037`, unchanged header/loader/manifest hashes, valid application
  checksums, exact stock restoration and normal `10f5:5038` operation.
