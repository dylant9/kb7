# Firmware audit remediation status

This file maps every concrete finding in
`SECURITY-AUDIT-2026-08-17.md` to the public source after remediation. “Fixed”
means the source behavior is covered by an offline build or host test; it does
not mean the firmware is approved for hardware.

The later `SOC-DATASHEET-AUDIT-2026-08-18.md` supersedes the earlier CPU and
peripheral-identity assumptions. It adds dual-core startup, GPIO pinmux,
controller attribution, and clock derivation as release blockers. Those new
findings do not invalidate the source-level repairs below.

## Source defects repaired

| Finding | Disposition and evidence |
|---|---|
| Clock ROM result was inverted | Fixed. `0` and `0x00ffffff` are fatal results; other results pass, and the state-4 divider calculation is restored. `test_c_clock.py` covers both sentinels and both divider branches. A clock failure now requests the loader. |
| Core0 vector table was short | Fixed at 79 entries (through index 78). The linker requires exactly `0x13c` bytes and `make verify` checks the ELF symbol size. |
| Timeout counters wrapped | Fixed in DRAM and MCU2 with explicit zero checks before decrement. Public LCD/RGB/USB drivers contain no polling loops. Host tests execute true DRAM/MCU2 timeout paths, and the source audit rejects a reintroduced `timeout--` condition. |
| A3 Hall responses were treated like requests | Fixed. Only requests require the `aa bb cc dd ee` trailer; all 82 bytes after the A3 status are samples. `test_c_mcu2.py` deliberately uses non-trailer final samples. |
| Sensor index was used as HID usage | Removed. Hall events go through `kb7_keymap_lookup()` and no HID usage is generated from an unmapped selector. The public default map contains no guessed bindings. |
| Report ID `0x03` had incompatible meanings | Fixed in the project-owned report model. Keyboard=`0x04`, consumer=`0x05`, analog=`0x06`, vendor control=`0x5c`; each has one fixed shape. `test_c_usb_reports.py` covers IDs and sizes. |
| Key/media releases were missing | Fixed. Touch actions emit down/up, encoder media actions emit press then zero, modifiers use HID usages E0–E7, and physical plus touchscreen keyboard sources are merged. |
| Sliders/toggles were immutable | Fixed. UI state is separate from the immutable store; sliders derive a clamped value from touch X on down/move/up and toggles change once on down. `test_c_ui.py` covers the event sequence and values. |
| Storage selected header-only validity | Fixed. Header, reserved bytes, complete payload CRC, and wrap-safe generation order are checked before selection. The C NOR test proves corrupt-newest fallback and that BEGIN preserves the surviving slot. |
| Screen parser accepted noncanonical input | Fixed. C, Python, and browser paths require exact length/layout, zero v1 flags/reserved fields, exact screen/widget partitioning, unique IDs, known opcodes, action-specific ranges/navigation targets, and valid UTF-8. `test_c_parser.py` compares C and Python over every truncation and a deterministic mutation corpus. |
| Host server omitted documented behavior/statuses | Fixed at the protocol layer: validation distinguishes version from CRC failures; BEGIN/WRITE/COMMIT are strict; READ, runtime SELECT, and confirmed FACTORY RESET are implemented. The C host-server test exercises the state machine against simulated NOR. |
| Touch SCL was driven high | Fixed. Both I²C lines now use release-for-high/open-drain behavior and SCL release has a bounded clock-stretch wait. Touch remains disabled by default pending electrical validation. |
| Faults slept forever/recovery check was late | Improved. The recovery chord is sampled before the ROM clock transition, clock failure requests the loader, and every default core0 vector records an error then requests the loader. External recovery is still required before hardware testing. |

## Findings handled by fail-closed boundaries

These cannot be honestly completed without redistributable board data and
hardware measurements:

- USB enumeration remains disabled. There is no claim of an EP0 state machine,
  endpoint DMA lifecycle, VID/PID, or usable live transport.
- LCD and RGB profiles remain omitted and disabled. The common layer now offers
  tick-based millisecond delay support, but no recovered private panel sequence
  or stale RGB packet is published.
- MCU2, touch, RGB, display, encoder, and unverified DRAM bring-up all default to
  zero in `config.h`; public core1 does not drive those buses.
- The exact 82-selector physical key map remains absent. An unmapped selector
  cannot become an accidental HID usage.
- NOR erase/program remain fail-closed in the public driver. The updater logic
  is testable with an injected host NOR model but cannot mutate device flash.
- A full external-programmer backup/restore and verified MCU reset hold remain
  mandatory before an independent core0 experiment.

## Release-pipeline findings

The public build emits ELF/disassembly files for inspection only and has no
binary extraction or bundling path. Consequently an ELF/raw mismatch, partial
stock anchoring, an empty flash plan, stale experiment payload, or escaped output
path cannot be approved by this repository. `make bundle` fails intentionally,
generated/vendor artifacts are rejected by `check_public_tree.py`, header
dependencies use `-MMD -MP`, and `audit_firmware_source.py` protects the
fail-closed defaults.

Any future image-producing release pipeline must, before it is enabled:

1. derive every payload from its named ELF in the same invocation and compare it
   byte-for-byte;
2. hash-pin every recovery-critical stock input, not only core1;
3. require a non-empty, bounded `flash-plan.json` and validate every plan range;
4. confine all outputs to the requested output directory; and
5. pass independent hardware recovery, USB, display, RGB, Hall-map, and NOR tests.

## Current verdict

The audited source defects are incorporated, but the public firmware is still a
non-flashable engineering implementation. In addition to missing hardware
profiles and recovery evidence, the later datasheet audit requires a corrected
dual-core model, GPIO/pinmux implementation, MCU2 controller attribution, and
clock derivation. None is silently enabled.

## Verification record

The final offline verification pass completed successfully on 2026-08-18:

- `make check`: 38 Python/C integration tests passed, browser JavaScript syntax
  checked, and both firmware profiles built and passed ELF verification;
- default profile sizes: core0 `0x454` bytes total, core1 `0x1404` bytes total;
- all-guarded-path audit profile sizes: core0 `0x528` bytes total, core1
  `0x21cc` bytes total;
- neither ELF contains unresolved relocations, and core0's vector table is
  exactly `0x13c` bytes;
- the public-tree policy check accepted 96 UTF-8 source/documentation files and
  found no firmware blobs, generated binaries, or disallowed material; and
- independent warning passes using GCC `-fanalyzer` and strict conversion,
  shadowing, and undefined-macro diagnostics completed without findings.
