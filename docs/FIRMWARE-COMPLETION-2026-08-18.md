# Firmware implementation completion and pre-flash status

Review date: 2026-08-18
Updated with recovery and USB-ISP validation evidence: 2026-08-23
Scope: independently authored public source after the missing-function work
Replacement firmware exercised on hardware: none
Stock recovery exercised: full-chip external ESP32-C3 restore/verification and boot
Stock loader re-entry: statically proved in V1.22/V1.24/V1.33; custom proof hardware-unrun
Fixed proof install/restore campaign: owner-bound and independently reverified offline; live disabled

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
remains behind a board-profile gate, and several dynamic controller assumptions
still require hardware validation. The first hardware
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

The stock application-side path back to that loader is now statically closed as
well. Hash-pinned V1.22, V1.24 and V1.33 evidence proves the marker write,
SRAM-relocated routine, exact 64-KiB XIP-to-PRAM copy, AIRCR reset and early
loader marker consumer. An independently authored minimal proof profile passes
offline and contains no application, USB-init or flash-mutation path. It is
default-off and has not run on hardware, so this result does not yet claim a
custom-firmware transition to `10f5:5037`. See the
[stock loader-reentry proof](STOCK-LOADER-REENTRY-2026-08-23.md).

The exact proof-install and stock-restore software is now also present. It keeps
the stable Core-1 target byte-exact stock, uses one temporary fixed Core-1
sector checksum poison while rebuilding Core 0, commits a rank-32 Core-0 gate
last, and derives the reverse sequence to the exact full baseline. Its separate
executor has terminal pre-USB intents, two exact pre/post full-chip reads,
strict close-before-publication, no raw flash fields and no ordinary USB
reconciliation. Supporting source and policy hashes are pinned, and live
execution is enabled only for the exact bounded proof campaign. The supplied
pair of exact owner baselines now
reproduces the pinned 168-operation campaign, its checksum-valid proof target,
and its byte-exact stock-restoration target. See the
[fixed proof campaign](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md).

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
- Ordinary recovery requests record and read back the stock mailbox marker,
  disable interrupts and park. Behind a separate default-off validation gate,
  the clean-room proof instead follows stock: execute from shared SRAM, replace
  PRAM with the preserved loader, then request AIRCR reset. AIRCR alone still
  only restarts the current PRAM image.
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
`KB7_MCU2_BOARD_PROFILE_VERIFIED=1`. The SNC logical 14–17 SPI0 mode-4 route is
now known, as are the peer AT32F423 SPI3 AF6 pins; the remaining gate concerns
end-to-end behavior and Hall calibration.

### Display, touch and RGB

- Recovered panel reset and 9-bit command path, full command stream and exact
  delay/order correction (`100 ms`; `35/62/11`; `120 ms`; `29`; `20 ms`).
- Bounded PPU/LCDC setup, 480×800 active geometry, 1,920-pixel framebuffer
  stride and line-descriptor generation. LCDC makes no controller MMIO writes
  unless every required parallel-bus function-1 route is known; the recovered
  default P2.4–P3.9 group now satisfies that check.
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
- A separate offline Ed25519 tool revalidates that complete bundle before
  creating or checking a detached authentication envelope. It requires a
  separately pinned public-key fingerprint and cannot authorize execution.
  The mechanism is tested, but a project release key and trust policy are not
  provisioned; see `OFFLINE-UPDATER-AUTHENTICATION-2026-08-23.md`.

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
- GPIO electrical pulls and `SYS0_PINCTRL` exceptional group routing are
  distinct. The mode columns are peripheral priorities, not a generic per-pad
  field. The driver implements ordinary GPIO, the default LCD mode-1 and SPI0
  mode-4 groups, and the stock-proven P0.6 PWM selector.
- Backlight is P0.6/`CT32B6_PWM1` mode 7.
- POR/external/LVD/DPD/watchdog reset enter ROM; software reset restarts PRAM.
- RSTN is package lead 88 for the expected LQFP128 device. The board's
  `MCU_RST` measured about 3.2 V released and 0.2 V when pulled to ground
  through 1 kΩ during two successful reads and was used for a successful full
  restore. Direct lead-88 continuity remains unmeasured but is optional for the
  demonstrated recovery procedure.

## Remaining hardware-only gates

These are not honest candidates for further offline coding:

The stop-gated measurement order and exact macro/evidence mapping are now in
`BOARD-VALIDATION-PLAN-2026-08-23.md`. Its first session performs no custom
execution and no firmware-region write.

1. Preserve the demonstrated `MCU_RST` external-SPI full-stock
   restore/readback procedure and exact hashes. Complete marking and direct
   lead-88 continuity would improve documentation but are no longer treated as
   prerequisites for the already-demonstrated isolation method.
2. Passively capture post-boot SYS0/SYS1, OPI/DRAM and cache state or validate
   the reconstructed cold-start sequence on an isolated board.
3. Retain the statically recovered pinmux model: LCD uses the default P2.4–P3.9
   mode-1 group, MCU2 uses the default P0.14–P1.1 SPI0 mode-4 group, and P0.6
   PWM sets bit 17. No stock-powered pinmux capture is required for these routes.
4. Verify USB PHY attach, IRQ6, DMA actual-length semantics, EP0 address
   application, halt/toggle, suspend/resume and sustained IN/OUT/mailbox traffic;
   obtain a legally assigned VID/PID.
5. Functionally validate the recovered MCU2 SPI0/AT32 SPI3 exchange and ready
   line, then calibrate Hall idle/full-travel/noise on the physical switches.
6. Verify functional display timing and framebuffer scanout; verify
   touch reset/address/coordinates and measure end-to-end touch report rate.
7. Verify RGB electrical mode/latch behavior and correlate all 101 LEDs with
   physical key legends before enabling per-key effects.
8. Verify action-bar GPIO continuity, active-low polarity and safe pulls before
   enabling its board-profile gate.
9. Maintain the successful external-SPI reset/programmer recovery runbook before
   any combined image is written. The stock software loader-entry route is now
   statically proved across three releases, and its default-off clean-room proof
   passes offline, but the required bounded hardware run has not occurred. Until
   `10f5:5037`, immutable-region hashes, exact stock restoration and normal
   `10f5:5038` are observed, it is not an operational recovery claim. The
   fixed proof campaign and executor now pass owner-bound offline simulation,
   exact operation rederivation and fault testing. The exact campaign ID is
   pinned, and the exact bounded hardware proof is independently authorized but
   remains unrun. The general
   paired-firmware executor remains mutation-locked
   and external SPI remains the final recovery route. The narrow marker and guarded erase-
   footprint experiments passed at their fixed stock-loader scratch targets,
   but are not a supported flasher and do not install these replacement images.
   A separate fixed multi-sector and
   process-restart scratch experiment has now passed once: two
   command-complete/no-readback operations reconciled to exact postimages in
   new processes, cleanup restored the complete baseline, and normal `5038`
   operation returned. The later fixed scratch executor's v1 source also
   completed its distinct 22-operation, one-process-per-boundary plan once;
   final read-only reconciliation and a separate verifier invocation reproduced
   complete-image
   SHA-256
   `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`,
   after which the owner reported normal `5038` operation. The historical v2
   executor also completed once. Its mandatory
   command-complete/no-postread active intent exited 4 after `program-09` and
   WIP ready; a fresh verifier-only process accepted two exact boundary-10
   postimage reads without retry; the remaining plan restored the exact
   baseline and cleared state; a separate verifier passed all three region CRCs;
   and the owner confirmed normal operation. The current v3 executor has also
   completed once. Its fixed checkpoint instead self-terminates with signal
   9/status 137 after validated program CSW and durable/read-back command-
   complete state, before WIP polling, postread or explicit USB close.
   Preflight-started and raw-intent markers are published before backend
   construction or USB and are terminal if left visible. Only exact command-
   complete and final-complete states are reconcilable; each consumes a one-shot
   started state before USB and closes strictly before final publication. Atomic
   ambiguity permits only local inspection, never USB. Status 137 is operator-
   observed, not journal-bound; status 126 permits cleanup only and does not
   validate continuation. The observed v3 run returned status 137; fresh-
   process reconciliation accepted the exact postimage without replay; the
   remaining steps restored and cleared the exact baseline; all three region
   CRCs passed; and the owner confirmed normal `5038` keyboard operation. Both
   verifier and executor use the same loader/SoC
   `F6 05` read path. None of these runs tests physical mid-command interruption
   or power loss, and none touches firmware regions.
   See `USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md` and
   `USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md`; the v3 plan and
   result are in `USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md`
   and `USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md`.

## Build and test profiles

- `make -C replacement_fw clean all`: fail-closed public/default ELF build.
- `make -C replacement_fw audit-profile`: compile feature code with board and
  flash-mutation gates still closed.
- `make -C replacement_fw integration-check`: compile every hardware branch,
  including explicit board-profile and flash-mutation gates. This is code
  coverage, not board approval.
- `make -C replacement_fw recovery-proof`: build and structurally verify the
  minimal planner-compatible loader-reentry ELF. It produces no bundle, does
  not make the ELF checksum-compatible by itself, and touches no device.
- `python3 tools/flash-access/kb7-loader-reentry-campaign.py`: privately derive
  or reverify the exact fixed proof-install/stock-restore campaign from two
  owner baselines; it has no device I/O and does not authorize execution.
- `make check`: Python/browser tests, host-compiled C component/protocol tests,
  all four ARM profiles, hardware-fact validation and public-tree policy.

No build target flashes a device. Generated ELFs/maps/disassemblies are ignored,
and the public-tree checker rejects binaries, archives, vendor artifacts and the
restricted datasheet.
