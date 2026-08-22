# SNC7320 datasheet audit and physical pin map

Review date: 2026-08-18

## Executive result

The independent replacement firmware is **not flash-ready**. The SNC7320
datasheet makes a package-level physical pin map possible, validates several
memory and interrupt assumptions, and exposes additional release blockers:

- the low-level KB7 LCD software is present in the recovered application flash,
  not exclusively in SoC mask ROM; the SoC supplies the PPU/TFT/8080 hardware;
- the SoC contains two ARM Cortex-M3 processors, not one Cortex-M4;
- `0x10000000` is a shared 1-MiB I-cache execution window, not a dedicated
  second-core flash address;
- `0x20000000..0x20000fff` is the shared inter-core mailbox;
- `0x40022000`, `0x40023000`, and `0x40024000` are respectively the SPI-NOR,
  SD0/NAND, and SD/SDIO controllers;
- GPIO pull configuration and system pin multiplexing are separate mechanisms;
  the current driver separates them and rejects unpublished alternate-function
  encodings; and
- SysTick is now derived from the reconstructed active clock rather than a
  fixed 120-MHz assumption, while the PLL sequence still requires board proof;
- AIRCR/software reset restarts from PRAM, so it cannot by itself enter the
  preserved ROM/flash loader; and
- the documented PPU limit and an SPIFC/touch pin collision leave two important
  board-specific questions unresolved.

This review changes names and build settings only where the datasheet is
unambiguous. It does not invent register offsets or bit encodings omitted from
the public documentation.

## Sources and publication boundary

The architecture, memory, peripheral, package, and pinmux findings come from:

- Sonix, *SNC7320 Series Product Brief*, revision 2.3, 24 April 2024:
  <https://www.sonix.com.tw/webapi/fl218645/snc7320_brief_data_sheet_V2.3.pdf>
- Sonix, *SNC7320 Series Data Sheet*, revision 2.1, 1 June 2022, indexed at:
  <https://device.report/sonix/snc73200>
- Sonix, *SNC7320 Series Evaluation Board Manual*, including the reset and SWD
  example circuits:
  <https://www.manualslib.com/manual/2622886/Sonix-Snc7320-Series.html>

The complete datasheet carries an explicit Sonix redistribution restriction.
It is not included in this repository. This file is independently written and
records only the factual interoperability conclusions needed to review this
project. It is an engineering provenance decision, not legal advice.

The full product marking should be photographed before relying on the package
map. The observed abbreviated `SN73200M1N-000` marking is consistent with the
`SNC73200M1NLFG-000` device: LQFP128L, 80 GPIOs, and 8 MiB SiP OPI PSRAM. A
different package or pinout suffix invalidates the lead numbers below.

The reviewed 94-page PDF has SHA-256
`d360aca16c2695f12edf91d263b2994b36edf5ad6faf130547a9220dfaca94b4`.
Its PDF page numbers and printed footer page numbers coincide. Citations below
refer to that revision. The PDF itself is deliberately excluded from this
repository.

## Primary LCD-driver answer

The low-level LCD software needed by the KB7 is in the recovered application
flash. It is **not dependent on an undiscovered mask-ROM LCD service**.

The evidence separates hardware from software:

- the silicon contains the PPU at `0x40050000` and built-in TFT/8080 output
  hardware (Data Sheet pp. 36 and 66–69);
- the recovered flash contains the panel-reset and 9-bit command serializer,
  panel command stream, PPU programming, display descriptors, framebuffer
  movement, and vblank path summarized by the independently authored driver and
  firmware-completion record;
- the closed display call graph does not enter either resolved Core-0 ROM call;
  the datasheet now identifies the `0x40022000` block used by the surviving ROM
  transition as the SPI-NOR controller, not the display block (pp. 36–38); and
- the datasheet describes internal USB/FAT libraries and Core-1 DSP programs,
  but names no LCD library (p. 35). That omission is supporting context, not the
  proof—the flash-resident display call graph is the proof.

Reimplementing that driver still requires exact, redistributable pinmux/clock
fields and a hardware-validated panel profile. A mask-ROM dump is useful for
boot and clock research, but it is not a prerequisite for reconstructing the
LCD behavior.

## Architecture corrections

### CPU and execution regions

The device has two ARMv7-M Cortex-M3 processors, each documented for
operation up to 162 MHz. Core 0 controls system operation and boots Core 1;
both processors can access the shared SRAM, mailbox, peripherals, external
memory, and I-cache window. The cache controller can serve only one core at a
time, so access is not equivalent to simultaneous ownership (pp. 29, 37,
40–41).

The existing `core0` and `core1` filenames are retained as legacy package-region
names. They must not be read as proof that each file is an independent CPU
image:

| Address | Datasheet meaning | Project consequence |
|---:|---|---|
| `0x00000000` | Core 0 PRAM after remap; Core 1 local ROM | Core 0 owns the external vector image; Core 1 startup is not represented by a second vector table in this tree. |
| `0x08000000` | Core 0 64-KiB boot ROM | Recovered ROM calls remain Core-0-specific until demonstrated otherwise. |
| `0x10000000..0x100fffff` | Shared 1-MiB I-cache window | The legacy region-1 entry is executable by Core 0 and is not itself a second-core release operation. |
| `0x18000000..0x1803ffff` | 256-KiB shared AHB SRAM | Current linker regions fit, but both-core ownership and stack high-water remain unaudited. |
| `0x20000000..0x20000fff` | 4-KiB shared mailbox RAM | The loader flag at `0x20000ffc` occupies the final mailbox word and must be reserved from IPC. |
| `0x30000000..0x307fffff` | 8-MiB OPI PSRAM on the M1 device | Both recovered framebuffers fit; initialization and training remain unverified. |
| `0x60000000..0x6fffffff` | SPI-NOR XIP window | The installed 32-MiB flash lies within the controller window. |

These ranges are from Figure 5-1 and Tables 5-1/5-2 (pp. 35–37). The
datasheet's 16-KiB I-cache figure is physical cache capacity; 1 MiB is the
mapped execution aperture.

The prototype currently makes an ordinary Thumb call from Core 0 to the legacy
region-1 entry. That can be a deliberate Core-0-only architecture only if the
second processor is proven held inactive. Before hardware execution, the
project must locate the Core 1 reset/release controls, inspect both cores over
SWD, and either start Core 1 with a valid vector/stack/IPC contract or keep it
deterministically quiescent.

The public Makefile now targets `-mcpu=cortex-m3`. Both the default and guarded
audit profiles also built successfully as Cortex-M3 before this change; their
ELF attributes reported ARMv7-M and no M4-only instruction was found. This
establishes instruction compatibility, not correct dual-core startup.

### Peripheral base-address corrections

The datasheet memory map and DMA-channel table resolve three formerly inferred
blocks (pp. 36–37):

| Base | Datasheet block | Public source disposition |
|---:|---|---|
| `0x4000e000` | SPI0 | The recovered A3/MCU2 protocol object selects serial instance 0 and transfers through this block; the clean-room driver now uses it behind the MCU2 gate. |
| `0x4000f000` | SPI1 | Corroborates the recovered, feature-gated RGB driver and controller packets. |
| `0x40022000` | SPI-NOR flash controller (SPIFC/SFC) | Public symbol corrected. The recovered ROM transition targets this controller. |
| `0x40023000` | SD0/NAND controller | Public symbol added; it must not be used as SPI-NOR. |
| `0x40024000` | SD/SDIO controller | Public symbol corrected. A later trace disproved the old MCU2 attribution: the A3 path uses SPI0, not this block. |
| `0x40040000` | DDR1/OPI memory controller | Base corroborated; the M1 part uses OPI PSRAM. |
| `0x40050000` | PPU/display block | Corroborates the recovered display controller region. |
| `0x40100000` | USB device controller | Base corroborated; the public stack implements EP0/endpoints behind a zero-identity board gate. |
| `0x45000000` | System Control 0 | Base corroborated; register offsets still require the separate register reference or stock-code proof. |
| `0x45000100` | System Control 1 | Relevant to clock/reset and likely second-core control. |
| `0x45000300` | PMU | Relevant to power-state validation. |

The documented IRQ table (pp. 31–32) independently supports these identities: IRQ6 is USB
device and IRQ15 is SDIO. It documents external IRQ0 through IRQ56, ending at
vector index 72. The public 79-word vector table therefore covers every
documented vector plus the additional entries present in the stock table.

### GPIO and pinmux blocker

The datasheet separates two concepts (pp. 24–27, 43 and 45):

1. per-port `GPIO_PnCFG` fields select inactive, pull-up, pull-down, or repeater
   electrical behavior; and
2. `SYS0_PINCTRL` selects peripheral modes 0 through 7.

The current `kb7_gpio_configure()` now treats the two-bit per-port field only as
electrical pull/repeater configuration. `SYS0_PINCTRL` is handled separately;
ordinary GPIO and the one proven P0.6 PWM route are supported, while other
alternate functions are rejected until their encoding is recovered.

The backlight correction is implemented: P0.6 uses `CT32B6_PWM1` mode 7. LCD
parallel mode 1 and SPI0 mode 4 remain fail-closed pinmux blockers.

The missing `SNC7320_reg_vx.xx` register reference is still needed for exact
`SYS0_PINCTRL`, pull, drive-strength, clock/reset, and interrupt bitfields. In
its absence, the acceptable alternatives are complete stock-code recovery plus
hardware observation; guessing is not acceptable.

### Clock and timing blocker

The documented clock tree (pp. 32–34) has:

- a 12-MHz reset/default source;
- a 276–324-MHz system PLL divided by two, allowing CPU operation up to
  162 MHz;
- a separate 480-MHz USB PLL; and
- a maximum 40.5-MHz SPI-NOR clock.

The firmware now derives SysTick from the reconstructed active clock and uses
bounded delays throughout. The recovered PLL and peripheral-divider sequence
still must be confirmed by a passive register capture or isolated hardware
measurement before its frequency assumptions can be treated as board-validated.

## LQFP128 package-to-KB7 map

These are top-view package lead numbers for the SNC73200 MxNLFG LQFP128
assignment. Package numbering begins at the marked pin-1 corner and proceeds
counter-clockwise. Firmware-derived functions retain their prior confidence;
the datasheet proves only the package lead associated with each Pn.m signal
(pp. 11 and 19–28).

### Reset and debug

| Function | SoC signal | Lead | Status |
|---|---|---:|---|
| Board `MCU_RST` pad candidate | RSTN | 88 | Strong; require powered-off continuity. RSTN is active-low. |
| Wake input | WKPN | 89 | Datasheet-proven pad; KB7 routing unknown. |
| Trace output / GPIO logical 69 | SWO / P4.5 | 11 | Datasheet-proven. |
| SWD clock / GPIO logical 70 | SWCLK / P4.6 | 12 | Datasheet-proven. |
| SWD data / GPIO logical 71 | SWDIO / P4.7 | 13 | Datasheet-proven; the datasheet recommends an external pull-up. |

The evaluation-board reset circuit uses a pull-up and capacitor on RSTN and a
switch that pulls it to ground. On the KB7, verify `MCU_RST` to lead 88 and
measure its released voltage before relying on it for external-flash isolation.

### Statically recovered KB7 functions

| Logical | SoC signal | Lead | Recovered KB7 function |
|---:|---|---:|---|
| 0 | P0.0 | 120 | ST1633i touch SCL, bit-banged |
| 1 | P0.1 | 122 | ST1633i touch SDA, open-drain style |
| 2 | P0.2 | 66 | Display glue auxiliary input |
| 3 | P0.3 | 64 | Display glue auxiliary input |
| 4 | P0.4 | 79 | Panel reset |
| 5 | P0.5 | 80 | Panel 9-bit DATA/D-C |
| 6 | P0.6 | 81 | Display backlight, `CT32B6_PWM1` mode 7 |
| 12 | P0.12 | 121 | ST1633i interrupt input |
| 18 | P1.2 | 112 | Peripheral enable/power candidate |
| 19 | P1.3 | 111 | MCU2 SPI ready/status input; electrical polarity remains to be captured |
| 26 | P1.10 | 117 | ST1633i reset |
| 32 | P2.0 | 31 | RGB bank/control 0 candidate |
| 33 | P2.1 | 30 | RGB bank/control 1 candidate |
| 35 | P2.3 | 26 | RGB chip-select/latch-style control |
| 58 | P3.10 | 32 | RGB reset/power candidate |
| 60 | P3.12 | 128 | RGB/SPI1 auxiliary or chip-select candidate |
| 64 | P4.0 | 40 | Action Bar/direct key 3 |
| 66 | P4.2 | 83 | Panel serial clock |
| 67 | P4.3 | 84 | Panel active-low chip select |
| 68 | P4.4 | 10 | System power/sleep control candidate |
| 72 | P4.8 | 100 | Volume roller phase A |
| 73 | P4.9 | 98 | Volume roller phase B |
| 74 | P4.10 | 97 | Action Bar/direct key 4 |
| 75 | P4.11 | 94 | Action Bar/direct key 0 |
| 76 | P4.12 | 93 | Action Bar/direct key 1 |
| 77 | P4.13 | 92 | Action Bar/direct key 2 |
| 78 | P4.14 | 91 | Action Bar/direct key 5 |
| 79 | P4.15 | 90 | Action Bar/direct key 6 |

The recovered Action Bar bit order remains logical 75, 76, 77, 64, 74, 78,
79 for bits 0 through 6. Roller direction remains pending hardware correlation.

### LCD parallel bus

| LCD signal | SoC signal | Lead |
|---|---|---:|
| HSYNC | P2.4 | 109 |
| VSYNC | P2.5 | 108 |
| DE | P2.6 | 107 |
| DCLK | P2.7 | 106 |
| D0 | P2.8 | 105 |
| D1 | P2.9 | 104 |
| D2 | P2.10 | 77 |
| D3 | P2.11 | 76 |
| D4 | P2.12 | 75 |
| D5 | P2.13 | 74 |
| D6 | P2.14 | 73 |
| D7 | P2.15 | 72 |
| D8 | P3.0 | 71 |
| D9 | P3.1 | 70 |
| D10 | P3.2 | 61 |
| D11 | P3.3 | 60 |
| D12 | P3.4 | 59 |
| D13 | P3.5 | 58 |
| D14 | P3.6 | 57 |
| D15 | P3.7 | 56 |
| D16 | P3.8 | 53 |
| D17 | P3.9 | 51 |

The package assignment proves where the documented LCD alternate functions
exist. Continuity to the KB7 panel connector is still required before driving
them.

The datasheet describes normal PPU/TFT output only up to VGA 640×480 and RGB565
(pp. 66–69), while the recovered KB7 setup is a 480×800 display using a padded
or tiled 1920×800 descriptor geometry. The stock register profile—not a naive
linear 480×800 setup—must remain the authority until the mismatch is explained
on hardware.

### Controller-capable pads requiring board continuity

| Candidate interface | Signals and leads | Important caveat |
|---|---|---|
| SPI-NOR controller | CS P0.8/110; CLK P0.9/42; MISO/IO1 P0.10/119; MOSI/IO0 P0.11/39; IO2/WP P0.12/121; IO3 P0.13/44 | These are SoC-capable pads, not proof that every quad-data lead is routed on the KB7. P0.12 is also the recovered touch IRQ, making continuity especially important. |
| SPI1 / RGB candidate | CS P3.12/128; CLK P3.13/127; MISO P3.14/126; MOSI P3.15/125 | `0x4000f000` is now identified as SPI1. Correlate these leads with the SNLED27351 and the recovered auxiliary GPIOs. |
| SPI0 / MCU2 | CS P0.14/2; CLK P0.15/3; MISO P1.0/4; MOSI P1.1/5 in mode 4; ready/status P1.3/111 | V1.22 initializes the A3 protocol object with serial instance 0; the generic serial initializer resolves that instance to `0x4000e000`, and the A3 sender polls `+0x0c` and transfers at `+0x1c`. Continuity and electrical timing remain hardware checks. |
| SDIO / unassigned | CLK P1.14/45; CMD P1.15/43; D0 P2.0/31; D1 P2.1/30; D2 P2.2/27; D3 P2.3/26 | `0x40024000` and IRQ15 are SDIO, but they are not the recovered A3 transport. Several data pads overlap recovered RGB controls. |

The AT32 firmware proves that MCU2 uses its SPI3 pins, and the SNC trace now
proves that its peer is SPI0 rather than SDIO. Powered-off continuity from the
AT32 SPI3 pads to SNC leads 2–5, plus the ready/status net to lead 111, remains
the decisive board-level check.

P0.12 cannot simultaneously be a continuously routed touch interrupt and
active SPIFC IO2 without some board-level isolation or time multiplexing. The
likely explanations are single/dual-bit NOR operation, an incomplete recovered
assignment, or unobserved board glue. Do not enable quad mode until continuity
and a passive stock capture resolve this conflict.

## Reset and loader correction

The reset destinations are materially different (Data Sheet p. 43): POR,
external RSTN, LVR/LVD, DPD wake, and watchdog reset restart through ROM, while
software reset restarts PRAM. ROM then scans boot media, parses a load table,
loads PRAM, and uses software reset to enter user code; absence of an identifying
mark leads to USB-ISP mode (p. 44).

The previous `kb7_enter_loader()` implementation wrote a recovered mailbox
marker and issued AIRCR `SYSRESETREQ`. The datasheet proves that this does not
by itself reach ROM, and the custom PRAM reset path never consumes the marker.
The public helper now records the marker, disables interrupts, and parks for an
external reset instead of falsely claiming recovery. The boot-time recovery
chord also defaults off because it reaches the unverified GPIO/pinmux
abstraction. A genuine autonomous loader route still requires one of:

- a proven watchdog configuration that resets through ROM;
- a documented/remapped ROM reset path;
- external RSTN or power cycling; or
- direct external-flash recovery with the SoC held reset.

See `BOOT-RECOVERY-MODEL.md` for the operational procedure and remaining
unknowns.

## Datasheet limits and contradictions

This is a data sheet, not the missing `SNC7320_reg_vx.xx` register reference.
It establishes block bases, signal capabilities, limits, interrupts, and DMA
windows but not most usable register offsets or bit encodings. Revision 2.1
explicitly removed register summaries (revision history p. 4).

Known internal inconsistencies are preserved rather than silently normalized:

- the SVCall vector offset is printed as `0x18` on p. 31; ARMv7-M requires
  `0x2c`;
- Program RAM is marked read-only in Table 5-1 even though the boot description
  says ROM writes user code into it (pp. 37 and 44);
- the DMA prose claims 19 channels, while Table 5-3 lists 18 and omits I2S4 DMA
  (p. 37);
- the IRQ prose alternates between 56 and 57 sources; the numeric span is
  IRQ0–56 with IRQ2 reserved (pp. 31–32);
- USB device text both denies isochronous transfers and later lists isochronous
  endpoints (pp. 63 and 65);
- several absolute maximum values conflict with wider recommended ranges on
  pp. 79–80; and
- the package note that all pins are pulled up conflicts with the GPIO chapter's
  inactive default pull configuration (pp. 23 and 45).

Use the ARM architecture for exception layout, nominal—not contradictory
upper-limit—electrical values, and recovered/hardware evidence wherever this
datasheet is self-inconsistent.

## Required pre-flash gates

### Offline firmware gates

1. Model the two processors explicitly and prove the second-core reset/release,
   vector, stack, IPC, and peripheral-ownership behavior.
2. Recover `SYS0_PINCTRL` and GPIO pull/drive fields; test every requested mode
   against the datasheet table. Do not enable the current GPIO abstraction.
3. Keep the now-recovered SPI0 MCU2 transport behind a disabled board profile
   until leads 2–5/111, polarity, clock mode, and ownership are measured.
4. Derive the system, peripheral, USB, display, timer, OPI, and SPI-NOR clocks;
   remove fixed-cycle timing assumptions.
5. Audit all DMA descriptors for address range, alignment, length, completion,
   IRQ mapping, and ownership/coherency across both cores.
6. Prove SRAM and OPI bounds, static stack requirements, stack high-water, and
   non-overlap with the loader, mailbox, both cores, DMA, and framebuffers.
7. Implement real fault capture and deterministic recovery, including stacked
   PC/LR retention, watchdog boot-attempt rollback, and an independently proven
   path back to the preserved loader.
8. Complete USB EP0 enumeration and endpoint lifecycle, the exact key map, LCD
   and RGB board profiles, and NOR mutation. All remain fail-closed publicly.
9. Keep image generation disabled until an image is derived from its named ELF,
   independently audited, accompanied by a bounded flash plan, and verified by
   byte-for-byte readback.

### Hardware gates while stock firmware remains installed

1. Photograph the complete SoC marking, pin-1 corner, board revision, and both
   sides of the PCB.
2. With power removed, continuity-map RSTN, SWDIO, SWCLK, SWO, SPI-NOR, RGB,
   SDIO candidates, LCD, touch, and the AT32 SPI3 pins. Prefer nearby vias and
   series resistors over slipping directly on 0.4-mm package leads.
3. Power stock firmware with current limiting; record 3.3-V I/O, 1.2-V core,
   and 1.8-V OPI rails plus idle and maximum current.
4. Hold `MCU_RST` low and verify that SPI-NOR CS, CLK, and data lines are quiet
   or high-impedance before attaching an external programmer.
5. Enumerate SWD access ports and debug components, read Cortex CPUID, halt each
   core independently if supported, and record VTOR/MSP/PC and Core 1 state.
6. Capture the stock SPI-NOR, RGB, touch, LCD command, and MCU2 candidate buses
   passively. Do not inject a command while ownership is unresolved.
7. Prefer initial custom-code execution from Core 0 PRAM/shared SRAM over SWD.
   A power cycle then restores stock without changing external flash.

### External-flash recovery gate

Before any device write:

1. hold the SoC in reset and read the complete 32-MiB flash twice;
2. require identical hashes and store independent backup copies;
3. record JEDEC ID, status/configuration registers, protection, quad-enable, and
   4-byte-address state;
4. prove a complete restore followed by an identical readback and normal stock
   boot;
5. use verified sector-aware read-modify-write operations—never whole-chip
   erase; and
6. preserve the flash header, loader, stock recovery code, and vendor assets.

Common black CH341A boards must not be assumed to provide 3.3-V-safe logic.
Measure the programmer or use a known-safe 3.3-V programmer. When the keyboard
is USB-powered, do not also connect programmer VCC; share ground and verified
logic signals only.

The datasheet proves that this M1 device's 8-MiB SiP memory is volatile OPI
PSRAM, not firmware flash (pp. 10 and 83). Persistent firmware therefore resides
in a separate boot device. A CH341-class SPI-NOR programmer is architecturally
appropriate only after the external flash marking, JEDEC ID, voltage, capacity,
and protection state are identified from the flash vendor's own data. The SoC
datasheet alone cannot approve a specific programmer or in-circuit wiring.

## Current verdict

The datasheet improves confidence in package pins, memory capacity, interrupt
coverage, reset behavior, and peripheral base addresses. It simultaneously
disproves the old Cortex-M4/single-core model, the inferred identities of two
storage controllers, and the former software-reset loader claim. The public
tree remains useful for offline architecture, parser, protocol, storage, UI,
and build testing, but no current ELF should be converted to a device image or
flashed.
