# SNC7320 datasheet audit and physical pin map

Review date: 2026-08-18

## Executive result

The independent replacement firmware is **not flash-ready**. The SNC7320
datasheet makes a package-level physical pin map possible, validates several
memory and interrupt assumptions, and exposes additional release blockers:

- the SoC contains two ARM Cortex-M3 processors, not one Cortex-M4;
- `0x10000000` is a shared 1-MiB I-cache execution window, not a private
  second-core flash address;
- `0x20000000..0x20000fff` is the shared inter-core mailbox;
- `0x40022000`, `0x40023000`, and `0x40024000` are respectively the SPI-NOR,
  SD0/NAND, and SD/SDIO controllers;
- GPIO pull configuration and system pin multiplexing are separate mechanisms,
  while the current prototype combines them in an unverified abstraction; and
- the current fixed 120-MHz SysTick assumption is not established by the
  documented clock tree.

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

## Architecture corrections

### CPU and execution regions

The device has two symmetric ARMv7-M Cortex-M3 processors, each documented for
operation up to 162 MHz. Core 0 controls system operation and boots Core 1;
both processors can access the shared SRAM, mailbox, peripherals, external
memory, and I-cache window.

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
blocks:

| Base | Datasheet block | Public source disposition |
|---:|---|---|
| `0x4000e000` | SPI0 | No live public driver. |
| `0x4000f000` | SPI1 | Corroborates the recovered RGB serial-instance identity; RGB remains fail-closed. |
| `0x40022000` | SPI-NOR flash controller (SPIFC/SFC) | Public symbol corrected. The recovered ROM transition targets this controller. |
| `0x40023000` | SD0/NAND controller | Public symbol added; it must not be used as SPI-NOR. |
| `0x40024000` | SD/SDIO controller | Public symbol corrected. Any use for the MCU2 link is a board-specific repurposing hypothesis, not the peripheral's identity. |
| `0x40040000` | DDR1/OPI memory controller | Base corroborated; the M1 part uses OPI PSRAM. |
| `0x40050000` | PPU/display block | Corroborates the recovered display controller region. |
| `0x40100000` | USB device controller | Base corroborated; the public USB implementation remains a stub. |
| `0x45000000` | System Control 0 | Base corroborated; register offsets still require the separate register reference or stock-code proof. |
| `0x45000100` | System Control 1 | Relevant to clock/reset and likely second-core control. |
| `0x45000300` | PMU | Relevant to power-state validation. |

The documented IRQ table independently supports these identities: IRQ6 is USB
device and IRQ15 is SDIO. It documents external IRQ0 through IRQ56, ending at
vector index 72. The public 79-word vector table therefore covers every
documented vector plus the additional entries present in the stock table.

### GPIO and pinmux blocker

The datasheet separates two concepts:

1. per-port `GPIO_PnCFG` fields select inactive, pull-up, pull-down, or repeater
   electrical behavior; and
2. `SYS0_PINCTRL` selects peripheral modes 0 through 7.

The current `kb7_gpio_configure()` instead treats a two-bit per-port field as a
peripheral-function selector and uses another inferred bitfield for pulls. That
abstraction is not supported by the datasheet and must not be enabled on
hardware without reimplementation.

One error is directly demonstrable from the pinmux table: backlight P0.6 uses
`CT32B6_PWM1` in mode 7, while the current prototype requests function 1. The
LCD and RGB stubs prevent the normal application path from reaching that code,
but this is still a release blocker.

The missing `SNC7320_reg_vx.xx` register reference is still needed for exact
`SYS0_PINCTRL`, pull, drive-strength, clock/reset, and interrupt bitfields. In
its absence, the acceptable alternatives are complete stock-code recovery plus
hardware observation; guessing is not acceptable.

### Clock and timing blocker

The documented clock tree has:

- a 12-MHz reset/default source;
- a 276–324-MHz system PLL divided by two, allowing CPU operation up to
  162 MHz;
- a separate 480-MHz USB PLL; and
- a maximum 40.5-MHz SPI-NOR clock.

The current SysTick reload of `120000 - 1` assumes a 120-MHz CPU clock without
proving it. All millisecond delays, protocol timeouts, reset holds, display
delays, and polling rates therefore remain unvalidated. Firmware must derive or
measure the active system and peripheral clocks and program SysTick from that
result.

## LQFP128 package-to-KB7 map

These are top-view package lead numbers for the SNC73200 MxNLFG LQFP128
assignment. Package numbering begins at the marked pin-1 corner and proceeds
counter-clockwise. Firmware-derived functions retain their prior confidence;
the datasheet proves only the package lead associated with each Pn.m signal.

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
| 19 | P1.3 | 111 | Peripheral status input candidate |
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

### Controller-capable pads requiring board continuity

| Candidate interface | Signals and leads | Important caveat |
|---|---|---|
| SPI-NOR controller | CS P0.8/110; CLK P0.9/42; MISO/IO1 P0.10/119; MOSI/IO0 P0.11/39; IO2/WP P0.12/121; IO3 P0.13/44 | These are SoC-capable pads, not proof that every quad-data lead is routed on the KB7. P0.12 is also the recovered touch IRQ, making continuity especially important. |
| SPI1 / RGB candidate | CS P3.12/128; CLK P3.13/127; MISO P3.14/126; MOSI P3.15/125 | `0x4000f000` is now identified as SPI1. Correlate these leads with the SNLED27351 and the recovered auxiliary GPIOs. |
| SDIO / former MCU2 candidate | CLK P1.14/45; CMD P1.15/43; D0 P2.0/31; D1 P2.1/30; D2 P2.2/27; D3 P2.3/26 | `0x40024000` and IRQ15 are SDIO. Several data pads overlap recovered RGB controls, so the prior MCU2 assignment must be retraced rather than assumed. |

The AT32 firmware proves that MCU2 uses its SPI3 pins, but it does not prove
which SNC peripheral or package leads reach them. Powered-off continuity from
the AT32 SPI3 pads to the SNC candidates is the decisive next test.

## Required pre-flash gates

### Offline firmware gates

1. Model the two processors explicitly and prove the second-core reset/release,
   vector, stack, IPC, and peripheral-ownership behavior.
2. Recover `SYS0_PINCTRL` and GPIO pull/drive fields; test every requested mode
   against the datasheet table. Do not enable the current GPIO abstraction.
3. Re-trace the MCU2 transport with `0x40024000` identified as SDIO and isolate
   every board-level inference behind a disabled profile.
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

## Current verdict

The datasheet improves confidence in package pins, memory capacity, interrupt
coverage, and several peripheral base addresses. It simultaneously disproves
the old Cortex-M4/single-core model and the inferred identities of two storage
controllers. The public tree remains useful for offline architecture, parser,
protocol, storage, UI, and build testing, but no current ELF should be converted
to a device image or flashed.
