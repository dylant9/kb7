# Firmware audit remediation status

This file maps every concrete finding in
`SECURITY-AUDIT-2026-08-17.md` to the public source after remediation. “Fixed”
means the source behavior is covered by an offline build or host test; it does
not mean the firmware is approved for hardware.

The later `SOC-DATASHEET-AUDIT-2026-08-18.md` supersedes the earlier CPU and
peripheral-identity assumptions. It adds dual-core startup, GPIO pinmux,
controller attribution, and clock derivation as release blockers. Those new
findings do not invalidate the source-level repairs below.

The subsequent implementation wave is summarized in
`FIRMWARE-COMPLETION-2026-08-18.md`. It replaces several fail-closed stubs with
complete, gated clean-room drivers and persistent profiles. The tables below
are retained as the original remediation ledger.

The later
[stock-loader audit](STOCK-LOADER-REENTRY-2026-08-23.md) supersedes only the
recovery evidence available to that ledger: the original marker-plus-AIRCR
claim was still wrong, but stock's additional SRAM relocation and
loader-to-PRAM copy are now statically proved. The custom equivalent passes
offline, defaults off and has not run on hardware.

## Source defects repaired

| Finding | Disposition and evidence |
|---|---|
| Clock ROM result was inverted | Fixed. `0` and `0x00ffffff` are fatal results; other results pass, and the state-4 divider calculation is restored. `test_c_clock.py` covers both sentinels and both divider branches. A clock failure now requests the loader. |
| Core0 vector table was short | Fixed at 79 entries (through index 78). The linker requires exactly `0x13c` bytes and `make verify` checks the ELF symbol size. |
| Timeout counters wrapped | Fixed throughout DRAM, MCU2, LCD, RGB, USB, flash and clock paths with explicit zero checks before decrement. Host/MMIO tests execute representative timeout paths, and the source audit rejects a reintroduced `timeout--` condition. |
| A3 Hall responses were treated like requests | Fixed. Only requests require the `aa bb cc dd ee` trailer; all 82 bytes after the A3 status are samples. `test_c_mcu2.py` deliberately uses non-trailer final samples. |
| Sensor index was used as HID usage | Fixed with the recovered 80/82 routing and 85-entry logical HID table. Fn is handled internally, modifiers are explicit, and unmapped selectors emit nothing. |
| Report ID `0x03` had incompatible meanings | Fixed in the project-owned report model. Keyboard=`0x04`, consumer=`0x05`, Hall telemetry=`0x06`, gamepad=`0x07`, vendor control=`0x5c`; each has one fixed shape. `test_c_usb_reports.py` covers IDs and sizes. |
| Key/media releases were missing | Fixed. Touch actions emit down/up, encoder media actions emit press then zero, modifiers use HID usages E0–E7, and physical plus touchscreen keyboard sources are merged. |
| Sliders/toggles were immutable | Fixed. UI state is separate from the immutable store; sliders derive a clamped value from touch X on down/move/up and toggles change once on down. `test_c_ui.py` covers the event sequence and values. |
| Storage selected header-only validity | Fixed. Header, reserved bytes, complete payload CRC, and wrap-safe generation order are checked before selection. The C NOR test proves corrupt-newest fallback and that BEGIN preserves the surviving slot. |
| Screen parser accepted noncanonical input | Fixed. C, Python, and browser paths require exact length/layout, zero v1 flags/reserved fields, exact screen/widget partitioning, unique IDs, known opcodes, action-specific ranges/navigation targets, and valid UTF-8. `test_c_parser.py` compares C and Python over every truncation and a deterministic mutation corpus. |
| Host server omitted documented behavior/statuses | Fixed at the protocol layer: validation distinguishes version from CRC failures; BEGIN/WRITE/COMMIT are strict; READ, runtime SELECT, and confirmed FACTORY RESET are implemented. The C host-server test exercises the state machine against simulated NOR. |
| Touch SCL was driven high | Fixed. Both I²C lines now use release-for-high/open-drain behavior and SCL release has a bounded clock-stretch wait. Touch remains disabled by default pending electrical validation. |
| Faults slept forever/recovery check was late | Reclassified after the full datasheet review. At that remediation stage, the only supported conclusion was that marker plus AIRCR restarts the custom PRAM image, so the helper changed to marker-and-park and faults reached that fail-closed path. A later three-version audit recovered stock's missing SRAM relocation and loader-to-PRAM copy. The clean-room equivalent now passes offline behind a default-off gate, but hardware still must prove `10f5:5037`; the recovery chord separately defaults off. |

## Findings still handled by fail-closed boundaries

These cannot be honestly completed without redistributable board data and
hardware measurements:

- USB now has EP0, descriptors, DMA lifecycle, reports and a vendor mailbox,
  but VID/PID and the board-verification flag default to zero.
- LCD, touch and RGB implementations are present and feature gates default off.
  The SNC mode-priority model and stock V1.22/V1.24/V1.33 traces now establish
  the default LCD mode-1 group and the exceptional PWM bit.
- The recovered sensor→logical→HID map is present. Physical legend identity for
  four layout-dependent selectors and logical-key→RGB correlation remain
  unresolved.
- SFC mutation is implemented but compiled out by default and allow-listed to
  the four project-owned screen/profile slots.
- MCU2 needs both a feature gate and separate board-profile proof. Its SNC SPI0
  mode-4 route and the peer AT32F423 SPI3 AF6 pins are statically recovered;
  the remaining gate is functional board behavior, not a guessed mux value.
- Two identical external-programmer backups and an ESP32-C3 full-stock
  restore/verification rehearsal are now demonstrated. The labeled `MCU_RST`
  pad is operationally sufficient for that proven isolation procedure; direct
  lead-88 continuity would add documentation, not a prerequisite.
- Stock software loader entry is statically proved across V1.22, V1.24 and
  V1.33: the marker is followed by an SRAM-executed loader-to-PRAM copy before
  software reset, and the copied loader consumes it. The default-off custom
  proof passes offline but is hardware-unrun, so ordinary builds still
  marker-and-park. See the
  [stock loader-reentry proof](STOCK-LOADER-REENTRY-2026-08-23.md) and
  [boot/recovery model](BOOT-RECOVERY-MODEL.md).
- The fixed proof campaign now derives a checksum-valid proof Core 0 with
  byte-exact stock Core 1 and a reverse sequence to the exact baseline. A
  temporary one-sector Core-1 checksum poison protects every dense Core-0
  prefix, and the final Core-0 word is a rank-32 checksum gate. Its separate
  executor is dry-run-default, has terminal pre-USB intent states and no raw
  flash fields. Supporting source/policy pins and focused campaign/executor
  tests pass. Two exact owner baselines independently reproduce its pinned
  168-operation identity and exact proof/stock closure. The first committed
  read-only preflight stopped before boundary zero; two independent external-
  SPI reads proved exact stock closure and no write was needed. The revised
  preflight then passed exact USB reads, strict close, boundary zero and a
  normal working boot. A new pin authorizes only the fixed proof/install/restore
  campaign. See the
  [fixed proof campaign](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md) and
  [preflight validation](LOADER-REENTRY-PREFLIGHT-VALIDATION-2026-08-24.md).
- The recovery chord defaults off. Its input choice and boot-time semantics
  still need a dedicated review; generic `SYS0_PINCTRL` uncertainty is no
  longer the blocker.

## Release-pipeline findings

The ordinary public build emits ELF/disassembly files for inspection only and
`make bundle` still fails intentionally. The earlier manifest-changing
constructor is retained only as an audit artifact. A separate V1.22-only,
offline planner now derives paired replacement sector images from named ELFs and
two matching owner captures, preserves the manifest, and checks a bounded
transaction model without any device I/O or full image. Generated plans/images
and vendor artifacts remain rejected by `check_public_tree.py`. A separate
paired-firmware executor scaffold performs read-only live
preflight/reconciliation and durable journal binding; its journal filenames are
also rejected from the public tree, and its mutation adapter remains
hard-disabled. A distinct dry-run-default scratch executor can replay only 22
fixed non-firmware operations in the reviewed V1.22 erased gap. Its v1 plan
passed once on the development unit with exact baseline restoration and a
subsequent operator-reported normal keyboard operation. Its historical v2 plan
passes offline fake-transport/state tests and also completed once on the
development unit. Its mandatory fixed command-complete/no-postread active intent
exited 4 after WIP ready; fresh-process verifier-only reconciliation accepted two
exact postimage reads without retry; and the fixed continuation restored the
baseline, cleared state and returned to normal operation. The current v3 plan
passes offline fake-transport/state tests and has completed once on hardware. It
self-terminates with signal 9/status 137 after validated program CSW and
durable/read-back command-complete state, before WIP polling, postread or
explicit USB close. Preflight-started and raw-intent markers are published
before backend construction or USB and are terminal if left visible. Only exact
command-complete and final-complete states are reconcilable; each consumes a
one-shot started state before USB and closes strictly before final publication.
Atomic ambiguity permits only local inspection, never USB. Status 137 is
operator-observed, not journal-bound; status 126 permits cleanup only and does
not validate continuation. The v3 run observed status 137, reconciled the exact
postimage without replay, restored the exact baseline, passed all three region
CRCs and returned to operator-confirmed normal `5038` keyboard operation. No
revision physically interrupts a
flash command or pulse, tests device power loss or touches firmware regions,
and none unlocks firmware mutation.
The additional fixed loader-reentry executor is not a general updater: it can
accept only one independently rederived proof campaign and its owner-specific
campaign pin is exact. `LIVE_PROOF_CAMPAIGN_ENABLED` is true only for that
fixed campaign after the revised read-only preflight passed; the general
paired-firmware executor remains independently locked.
Header dependencies use `-MMD -MP`.

Any future image-producing release pipeline must, before it is enabled:

1. derive every payload from its named ELF in the same invocation and compare it
   byte-for-byte;
2. hash-pin every recovery-critical stock input, not only core1;
3. require a non-empty, bounded `flash-plan.json` and validate every plan range;
4. confine all outputs to the requested output directory; and
5. pass independent hardware recovery, USB, display, RGB, Hall-map, and NOR tests.

The detached Ed25519 authentication mechanism now covers the exact verified
offline bundle and an explicitly pinned publisher key. It is not an
image-producing or installation pipeline, no project trust root is provisioned,
and it keeps `flash_approved=false`. The remaining physical gates and their
no-write-first order are recorded in `BOARD-VALIDATION-PLAN-2026-08-23.md`.

## Current verdict

The audited source defects and the offline-implementable functions are
incorporated, but the public firmware is still a non-flashable engineering
implementation. Remaining blockers are functional board validation, cold-start
proof and an assigned USB identity; none is silently enabled. The
external-SPI stock restore/verification rehearsal is complete and remains the
final rollback route. The minimal loader-reentry profile passes offline and is
planner-compatible, not a checksum-compatible or hardware-approved image; no
replacement firmware has run on hardware. The fixed installer/restorer is
offline-ready and authorized only for the bounded unrun proof; this does not
change `flash_approved=false`.

## Verification record

The latest offline verification pass completed successfully on 2026-08-23:

- `make check`: 261 Python tests passed, browser JavaScript syntax
  and executable validator checks passed, and the default, guarded-audit,
  all-branches integration and minimal recovery-proof firmware profiles built
  and passed ELF verification;
- the largest all-branches profile used 8,564 bytes of core0 text, 12 bytes of
  core0 data and 3,792 bytes of core0 BSS; core1 used 19,128 bytes of text,
  4 bytes of data and 19,312 bytes of BSS;
- neither ELF contains unresolved relocations, and core0's vector table is
  exactly `0x13c` bytes;
- the public-tree policy check accepted 206 UTF-8 source/documentation files and
  found no firmware blobs, generated binaries, or disallowed material; and
- independent warning passes using GCC `-fanalyzer` and strict conversion,
  shadowing, and undefined-macro diagnostics completed without findings.
