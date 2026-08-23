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
| Faults slept forever/recovery check was late | Reclassified after the full datasheet review. AIRCR/software reset restarts PRAM and cannot prove entry to the preserved loader. The compatibility helper now records the recovered mailbox request, disables interrupts, and parks for external reset. Faults reach that fail-closed park; the recovery chord now defaults off because its GPIO configuration is also unproven. A ROM-entering reset and external recovery are still required. |

## Findings still handled by fail-closed boundaries

These cannot be honestly completed without redistributable board data and
hardware measurements:

- USB now has EP0, descriptors, DMA lifecycle, reports and a vendor mailbox,
  but VID/PID and the board-verification flag default to zero.
- LCD, touch and RGB implementations are present; feature gates default off and
  unpublished alternate-function pinmux values are rejected.
- The recovered sensor→logical→HID map is present. Physical legend identity for
  four layout-dependent selectors and logical-key→RGB correlation remain
  unresolved.
- SFC mutation is implemented but compiled out by default and allow-listed to
  the four project-owned screen/profile slots.
- MCU2 needs both a feature gate and separate board-profile proof; its required
  SPI0 function-4 pinmux is not guessed.
- Two identical external-programmer backups and an ESP32-C3 full-stock
  restore/verification rehearsal are now demonstrated. A verified MCU
  reset/SFC-idle waveform remains mandatory before an independent core0
  experiment.
- Autonomous loader entry remains unavailable. The recovered mailbox marker's
  lifetime and consumer are unproven, and software reset is explicitly a PRAM
  restart. See `BOOT-RECOVERY-MODEL.md`.
- The recovery chord defaults off. Its chosen inputs, pull configuration, and
  `SYS0_PINCTRL` behavior must be proven before it can become a safety feature.

## Release-pipeline findings

The ordinary public build emits ELF/disassembly files for inspection only and
`make bundle` still fails intentionally. A separate source-only constructor now
derives replacement payloads directly from named ELFs, hash-pins every supplied
stock recovery component and emits a bounded non-empty flash plan without a
full image. Generated/vendor artifacts remain rejected by
`check_public_tree.py`; header dependencies use `-MMD -MP`.

Any future image-producing release pipeline must, before it is enabled:

1. derive every payload from its named ELF in the same invocation and compare it
   byte-for-byte;
2. hash-pin every recovery-critical stock input, not only core1;
3. require a non-empty, bounded `flash-plan.json` and validate every plan range;
4. confine all outputs to the requested output directory; and
5. pass independent hardware recovery, USB, display, RGB, Hall-map, and NOR tests.

## Current verdict

The audited source defects and the offline-implementable functions are
incorporated, but the public firmware is still a non-flashable engineering
implementation. Remaining blockers are physical validation, unpublished
pinmux encodings and an assigned USB identity; none is silently enabled. The
external-SPI stock restore/verification rehearsal is complete and remains the
required rollback route, but no replacement firmware has run on hardware.

## Verification record

The latest offline verification pass completed successfully on 2026-08-23:

- `make check`: 118 Python/C integration tests passed, browser JavaScript syntax
  and executable validator checks passed, and the default, guarded-audit, and
  all-branches integration firmware profiles built and passed ELF verification;
- the largest all-branches profile used 8,108 bytes of core0 text, 12 bytes of
  core0 data and 3,792 bytes of core0 BSS; core1 used 18,860 bytes of text,
  4 bytes of data and 19,312 bytes of BSS;
- neither ELF contains unresolved relocations, and core0's vector table is
  exactly `0x13c` bytes;
- the public-tree policy check accepted 167 UTF-8 source/documentation files and
  found no firmware blobs, generated binaries, or disallowed material; and
- independent warning passes using GCC `-fanalyzer` and strict conversion,
  shadowing, and undefined-macro diagnostics completed without findings.
