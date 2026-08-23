# Firmware implementation completion and pre-flash status

Review date: 2026-08-18
Updated with recovery and USB-ISP validation evidence: 2026-08-23
Scope: independently authored public source after the missing-function work
Replacement firmware exercised on hardware: none
Stock recovery exercised: full-chip external ESP32-C3 restore/verification and boot

## Verdict and primary LCD answer

The low-level KB7 LCD driver is in the external application flash we recovered,
not hidden exclusively in the SNC7320 mask ROM. The recovered flash contains the
panel reset, 9-bit command serializer and command stream, PPU/LCDC programming,
line descriptors, framebuffer path and display update flow. The datasheet
corroborates that the SoC provides PPU/TFT/8080 *hardware* at `0x40050000`; the
closed display call graph does not call a ROM LCD service.

All substantial functions that can presently be implemented and tested
offline are now represented in source. That does **not** make the firmware
flash-ready. Public defaults deliberately park before application startup, USB
does not attach without an assigned identity and verified board profile, MCU2
cannot transmit until pinmux/continuity are proven, and several proprietary
controller assumptions still require physical validation. The first hardware
run must use a complete external-flash backup, a proven programmer wiring plan,
and `MCU_RST` held low.

Two bit-identical full stock reads and the later successful ESP32-C3 repair now
provide a real external recovery result. The initial post-repair boot problem
was traced to leaving the unpowered programmer connected to the SFC bus. This
was followed by an owner-confirmed full-chip restore/verification rehearsal and
matching post-repair captures. This establishes the development unit's external-
SPI rollback path, but does not validate any replacement-firmware hardware path.

The preserved V1.22 loader has also completed one guarded USB-ISP marker program
and erase cycle at offset `0x0008e000`, with exact complete-array postflight
comparisons and final restoration to the baseline. A second fixed cycle at
`0x000c6000` populated an entire sector plus immediate guards and observed an
exact 4-KiB programmed-data footprint at that target; cleanup restored the full
baseline and the keyboard then cold-booted normally. These remain bounded stock-
loader results, not an installation route for these replacement images.

## Completed software-owned work

### Boot, clocks, memory and recovery

- Cortex-M3 build target, 79-word vector table and USB IRQ6 vector.
- Corrected ROM clock return semantics: `0` and `0x00ffffff` are fatal.
- Recovered clock-divider behavior, clock-derived SysTick and microsecond/
  millisecond delay APIs.
- Bounded DRAM/OPI training and non-destructive validation, followed by a full
  region-1 copy/readback and I-cache-window verification before branching.
- Correct Core0-only interpretation of the legacy `core1` region. The physical
  second core is not falsely claimed to be started.
- Fault record containing stacked registers and SCB fault state in reserved
  mailbox RAM.
- Recovery request records the stock mailbox marker and parks for external
  reset. AIRCR is not used because the datasheet proves that it restarts PRAM.
- SFC reads plus gated sector erase/page program with finite waits, status/
  protection checks, source/destination constraints and complete readback.
  Mutation is restricted to screen and profile A/B ranges.

### USB and host control

- Device/configuration/string/HID/report descriptors and standard/HID EP0
  request handling, including multi-packet data, required ZLPs, SETUP abort,
  deferred address and malformed-request stalls.
- Recovered controller initialization, IRQ/global/endpoint dispatch, DMA TRB
  rings, endpoint reset/halt/toggle, OUT rearm and an eight-entry copied IN
  queue.
- Coherent report shapes: keyboard `0x04`/21 bytes, consumer `0x05`/3 bytes,
  Hall telemetry `0x06`/64 bytes, gamepad `0x07`/14 bytes and bidirectional
  vendor control `0x5c`/64 bytes.
- A bounded shared-SRAM mailbox carries complete vendor OUT reports from the
  Core0 USB stack to the region-1 application. A full mailbox increments a
  drop counter rather than overwriting an in-flight command.
- Region-1 application delivery is back-pressure safe: command responses and coalesced latest
  keyboard/consumer/gamepad state retry until the eight-entry Core-0 IN queue
  accepts them; consumer pulses preserve their restore packet. Analog/widget
  telemetry is coalesced below controls so it cannot starve releases.
- Strict BEGIN/WRITE/COMMIT/ABORT/READ protocol with transfer identity, ordered
  offsets, payload/frame CRCs and atomic slot finalization.
- A confirmed factory-reset attempt invalidates the live XIP screen reference,
  releases any touch-held host action, restores built-in profiles/neutral input,
  and renders the safe default even if a later sector erase reports failure.

The public USB profile uses VID/PID zero and `KB7_USB_BOARD_PROFILE_VERIFIED=0`,
so `kb7_usb_init()` returns before any USB MMIO or electrical attach.

### Keyboard, Hall input and analog output

- Exact recovered 85-entry default HID table and 80/82-sensor routing,
  including layout variants `0/2/3` versus alternate layout `1`.
- Proven Fn selector `0x4e`; internal pseudo-usage `0xf1` cannot escape to USB.
- Primary, Game, Easy-Shift and FN1 action tables with transparent fallback,
  NKRO bits, modifier handling and consumer actions. Physical and UI consumer
  sources are merged, with the held source restored after a temporary pulse.
- Exact recovered raw-Hall-to-`0..32` travel conversion, per-key actuation and
  Rapid Trigger state.
- Five mutable, validated in-memory profiles, matching the five indices proved
  by the stock configuration database. Profile selection resets transient
  key/Fn/filter state.
- Configurable analog output with deadzone, saturation, linear/exponential/
  S-curve response, smoothing, inversion, opposing-key cancellation and
  optional digital passthrough.
- Seven direct action-bar inputs with the recovered active-low model,
  three-sample debounce and press/release events; encoder media actions also
  release. Live sampling requires separate feature and board-profile gates
  because continuity, pull and polarity remain physically unverified.
- Correct A3 request/response distinction and all 82 sample bytes. The live
  link is SPI0 at `0x4000e000`, not SDIO at `0x40024000`.

MCU2 requires both `KB7_ENABLE_MCU2=1` and
`KB7_MCU2_BOARD_PROFILE_VERIFIED=1`, and additionally refuses initialization
until the logical 14–17 function-4 pinmux is known.

### Display, touch and RGB

- Recovered panel reset and 9-bit command path, full command stream and exact
  delay/order correction (`100 ms`; `35/62/11`; `120 ms`; `29`; `20 ms`).
- Bounded PPU/LCDC setup, 480×800 active geometry, 1,920-pixel framebuffer
  stride and line-descriptor generation. LCDC makes no controller MMIO writes
  unless every required parallel-bus function-1 pinmux route is known.
- ST1633-style open-drain bit-banged I²C with clock-stretch timeout, nine-clock
  recovery, reset/identity/geometry checks, bulk contact reads, bounds checking
  and lost-frame release handling. Only the proven portrait coordinate geometry
  is accepted; landscape is rejected until a rotation/mirroring transform is
  recovered.
- Correct SPI1 RGB initialization, two bank-select mechanisms, controller
  register sequence, `0x21 00` planar PWM packets (194/146 bytes), `0x24`
  brightness and 101 populated positions among 112 stable controller slots.
- Static, controller-order gradient/aurora, whole-keyboard reactive and global
  heatmap rendering. Physical per-key RGB is intentionally unavailable until
  the logical-key-to-controller-position correlation is measured.
- Runtime sliders/toggles, touch down/move/up, HID/media releases, profile,
  actuation, Rapid Trigger, brightness, color and effect actions.

### Persistent formats and release construction

- Existing strict `KBS1` screen parser and dual screen slots.
- New strict `KBP1` input/lighting profile parser, one-to-five fixed records,
  C/Python compiler compatibility and two `0x38000` profile slots in the
  documented `0x01c00000..0x01c70000` reservation.
- Two bit-identical full 32-MiB programmer reads exposed and corrected an unsafe
  earlier storage map. Stock-owned configuration at `0x01800000..0x01bfffff`
  and the upload store at `0x01f00000..0x01ffffff` are now prohibited; screen
  A/B slots are 1.25 MiB each at `0x01570000..0x017effff`.
- Payload CRC is checked during slot selection and both boot loaders retry the
  older CRC-valid generation when the newest object fails semantic parsing. A new transfer erases only the inactive
  slot, one sector at a time as WRITE reaches it. Screen and profile stores are
  independently selectable on the host protocol. Transfers have a 5-second
  inactivity timeout; committed content is applied on the next boot.
- Python CLI compilation/inspection and device-free transfer plans.
- The earlier source-only manifest-changing bundle constructor remains an
  offline audit artifact and is not an update plan. A newer V1.22-only planner
  takes two matching owner captures, derives raw payloads from named ELFs,
  inserts a symmetric build-pair ID, CRC-balances both regions against the
  unchanged manifest, and checks a poison/stage/sparse-gate transaction model.
  It emits no full image, contains no device I/O and remains unsigned,
  execution-unapproved and `flash_approved=false`; see
  `USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md`.

## Datasheet correctness cross-check

The implementation now reflects these material SNC7320 facts:

- ARMv7-M Cortex-M3, not Cortex-M4.
- `0x10000000` is the shared I-cache aperture; it is not proof of a second-core
  image.
- `0x18000000..0x1803ffff` is shared SRAM and `0x20000000..0x20000fff` is
  mailbox RAM.
- `0x4000e000`/`0x4000f000` are SPI0/SPI1;
  `0x40022000`/`0x40023000`/`0x40024000` are SFC, SD0/NAND and SDIO.
- `0x40040000`, `0x40050000` and `0x40100000` are OPI/DRAM, PPU/display and USB.
- IRQ6 is USB and the documented interrupt range fits the 79-word table.
- GPIO electrical pulls and `SYS0_PINCTRL` peripheral routing are distinct.
  The driver implements ordinary GPIO and the proven P0.6 PWM route; unknown
  alternate-function encodings fail closed.
- Backlight is P0.6/`CT32B6_PWM1` mode 7.
- POR/external/LVD/DPD/watchdog reset enter ROM; software reset restarts PRAM.
- RSTN is package lead 88 for the expected LQFP128 device. The board's
  `MCU_RST` measured about 3.2 V released and 0.2 V when pulled to ground
  through 1 kΩ during two successful reads; physical lead-88 continuity and a
  reset waveform still need measurement.

## Remaining hardware-only gates

These are not honest candidates for further offline coding:

1. Confirm the complete SoC marking/package and `MCU_RST`→RSTN lead-88
   continuity. Preserve the demonstrated external-SPI full-stock
   restore/readback procedure, exact hashes and reset-isolation evidence.
2. Passively capture post-boot SYS0/SYS1, OPI/DRAM and cache state or validate
   the reconstructed cold-start sequence on an isolated board.
3. Determine the unpublished generic `SYS0_PINCTRL` encoding, especially LCD
   bus mode 1 and SPI0 mode 4, by a register capture/stock trace and continuity.
4. Verify USB PHY attach, IRQ6, DMA actual-length semantics, EP0 address
   application, halt/toggle, suspend/resume and sustained IN/OUT/mailbox traffic;
   obtain a legally assigned VID/PID.
5. Capture MCU2 SPI0 polarity/timing/ownership and ready-line behavior, then
   calibrate Hall idle/full-travel/noise on the physical switches.
6. Verify LCD bus continuity, display timing and framebuffer scanout; verify
   touch reset/address/coordinates and measure end-to-end touch report rate.
7. Verify RGB electrical mode/latch behavior and correlate all 101 LEDs with
   physical key legends before enabling per-key effects.
8. Verify action-bar GPIO continuity, active-low polarity and safe pulls before
   enabling its board-profile gate.
9. Maintain the successful external-SPI reset/programmer recovery runbook before
   any combined image is written. Autonomous software loader entry remains
   intentionally unavailable. The narrow marker and guarded erase-footprint
   experiments passed at their fixed stock-loader scratch targets, but are not
   a supported flasher and do not install these replacement images; external
   SPI remains the required recovery route. A separate fixed multi-sector and
   process-restart scratch experiment has now passed once: two
   command-complete/no-readback operations reconciled to exact postimages in
   new processes, cleanup restored the complete baseline, and normal `5038`
   operation returned. It did not test physical mid-command interruption or
   power loss and did not touch firmware regions.

## Build and test profiles

- `make -C replacement_fw clean all`: fail-closed public/default ELF build.
- `make -C replacement_fw audit-profile`: compile feature code with board and
  flash-mutation gates still closed.
- `make -C replacement_fw integration-check`: compile every hardware branch,
  including explicit board-profile and flash-mutation gates. This is code
  coverage, not board approval.
- `make check`: Python/browser tests, host-compiled C component/protocol tests,
  all three ARM profiles, hardware-fact validation and public-tree policy.

No build target flashes a device. Generated ELFs/maps/disassemblies are ignored,
and the public-tree checker rejects binaries, archives, vendor artifacts and the
restricted datasheet.
