# Replacement-firmware board-validation plan — 2026-08-23

## Outcome sought

The next useful milestone is evidence about the board assumptions that still
hold the replacement firmware closed. It is **not** another flash-transport
fault campaign and it is not a firmware installation. The first session below
uses power-off measurements, stock-powered passive observation, and—only if it
can be made demonstrably non-erasing—a RAM/debug probe. External flash remains
byte-exact stock throughout.

No paired-firmware write is authorized by this plan. `flash_approved` remains
false, the paired executor remains mutation-locked, and `make bundle` continues
to fail.

## Entry conditions

Before touching the board:

1. Freeze the source revision and pass `make check`.
2. Retain two independent exact 32-MiB baseline captures and the proven full-
   chip ESP32-C3 restore/readback procedure.
3. Verify the programmer is physically disconnected for normal power-up and
   never leave its signal leads attached while it is unpowered.
4. Keep a current-limited 3.3-V-safe setup, oscilloscope or logic analyzer, and
   a written power/reset order at the bench.
5. Keep all raw photographs, captures, dumps, serial numbers, and logs outside
   the public tree. Publish only independently authored summaries and hashes.
6. Stop if the unit, wiring, flash identity, baseline, power rails, or reset
   behavior differs from the rehearsed recovery setup.

The recovery wiring and electrical cautions in
[`BOOT-RECOVERY-MODEL.md`](BOOT-RECOVERY-MODEL.md) are normative.

## Gate matrix

| Gate | Evidence required before enabling it | Related compile-time boundary | Current state |
|---|---|---|---|
| Package/reset | Complete SoC marking/package; powered-off `MCU_RST` continuity to RSTN lead 88; reset and SFC-idle waveform | recovery remains externally asserted; no feature macro substitutes for continuity | closed |
| Cold-start memory | Passive stock SYS0/SYS1, OPI/DRAM/cache state or an isolated RAM-only cold-start validation with bounds and readback | `KB7_ENABLE_UNVERIFIED_DRAM_INIT=0` | closed |
| Pinmux | Independently observed generic `SYS0_PINCTRL` encodings, especially LCD mode 1 and SPI0 mode 4, plus PCB continuity | display and MCU2 paths fail before unknown routes | closed |
| USB | PHY/attach voltage, IRQ6, endpoint/DMA/EP0/halt/suspend/traffic evidence and a legitimately assigned VID/PID | `KB7_USB_BOARD_PROFILE_VERIFIED=0`, VID/PID `0` | closed |
| MCU2/Hall | SPI0 polarity, timing, ownership, ready line, exact pinmux, Hall idle/full travel/noise | `KB7_ENABLE_MCU2=0`, `KB7_MCU2_BOARD_PROFILE_VERIFIED=0` | closed |
| LCD/touch | Bus continuity, panel timing/scanout, touch reset/address/coordinates/rate | `KB7_ENABLE_DISPLAY=0`, `KB7_ENABLE_TOUCH=0` | closed |
| RGB | Electrical mode/latch behavior and 101-position physical correlation | `KB7_ENABLE_RGB=0` | closed |
| Encoder/action bar | Continuity, pull state, polarity, debounce and release behavior | encoder disabled; action bar plus board-profile gates disabled | closed |
| Persistent flash | Board behavior and recovery proven before any custom storage mutation | `KB7_ENABLE_FLASH_MUTATION=0` | closed |
| Paired install | Every prerequisite above, provisioned release trust root, reviewed exact bundle, and rehearsed SPI rollback | paired executor has no mutation command | prohibited |

`audit-profile` and `integration-check` compile closed branches to prevent code
rot. Their sentinel feature defines and USB identity are not board evidence and
must never be deployed.

## First board session: no custom execution

### A. Powered off

1. Photograph both PCB sides, board revision, SoC/flash markings, pin-1 marks,
   reset pad, flash pins, and likely SWD pads.
2. Confirm ground and measure `MCU_RST` continuity to SNC73200 lead 88. Record
   meter mode, probe points, resistance, and uncertainty; do not infer
   continuity from the pad voltage already observed.
3. Trace flash CS/CLK/IO0–IO3 and supply to the SoC-capable SFC leads. Record
   series resistors, buffers, other masters, and whether an attached debugger
   could contend with the bus.
4. Identify candidate SWDIO/SWCLK/SWO pads by powered-off continuity only. Do
   not attach or run a debugger during this phase.

Passing A closes only the package/reset and wiring-identification prerequisites.
Any ambiguous package or reset result is `HOLD`, not a reason to guess.

### B. Stock firmware, passive observation

1. With the programmer completely removed, power through the normal path under
   current limit and capture 3.3-V I/O, 1.2-V core, 1.8-V OPI, and reset ramps.
2. Capture `MCU_RST` assertion/release and SFC CS/CLK activity. Confirm reset
   keeps the SoC from driving the flash before any external programmer is ever
   reattached.
3. Capture stock boot/activity on candidate LCD, touch, RGB, MCU2-ready and
   action-bar lines without driving them. Record voltage domains first.
4. Power down before moving probes. Cold-boot again with every probe/programmer
   removed and require normal `10f5:5038` keyboard operation.

Passing B supplies passive electrical facts. It does not authorize custom code,
enable a board-profile macro, or prove unpublished pinmux values by itself.

### C. Optional read-only SWD qualification

Attempt this only after A/B and only with a debugger configuration proven not
to issue unlock, mass erase, option-byte, reset-vector, or flash-program
commands. First test connect-under-reset and read-only identification while a
logic analyzer watches flash CS/CLK. Abort on any flash traffic not explained by
normal reset/boot or on any tool prompt offering erase/unlock.

If safe read-only access is not independently demonstrated, record `SWD HOLD`
and skip this phase. External SPI recovery is not permission to let a debugger
mass-erase the device.

### D. Optional RAM-only minimum probe

This is a separate reviewed experiment, not part of the first session. It may
be designed only after C passes. The first payload should live entirely in
volatile PRAM/SRAM, use a bounded stack, write one owner-selected SRAM marker,
touch no peripheral or flash register, then park. Its complete bytes, load
addresses, debugger command log, reset behavior, and post-test full-flash hash
must be reviewed before execution.

A RAM-only marker would establish debug/load/vector control without consuming
the much larger risk of a checksum-valid custom flash image. It would not prove
DRAM, USB, display, input, or recovery firmware.

## Later subsystem sequence

After the minimum RAM probe, validate one dependency at a time and return to a
known stock/full-flash state between campaigns:

1. bounded clocks plus SRAM fault record;
2. isolated OPI/DRAM training and complete readback;
3. recovered pinmux snapshots and non-driving GPIO input checks;
4. USB only after a legitimate identity and electrical profile exist;
5. MCU2/Hall input before any output-driven UI subsystem;
6. LCD, then touch, then RGB;
7. encoder and action bar; and
8. project-owned persistent A/B storage last.

Each campaign needs an exact source revision, explicit enabled macros, timeout
and fault behavior, expected measurements, abort criteria, power-down order,
full-flash post-check, and owner-local raw evidence. A failure is followed by
external-SPI inspection/restore; it is never worked around by enabling the next
gate.

## Decision rule for any future firmware-region trial

A paired-image trial remains prohibited until every gate it can reach is marked
passed by reviewed physical evidence, a release public key and independently
distributed fingerprint are provisioned, the exact offline bundle and detached
authentication verify, and the SPI recovery rehearsal is repeated in the final
bench configuration. Even then, authorization must be a separate reviewed
decision; neither a green build nor a valid signature supplies it implicitly.
