# Replacement firmware source

This is a freestanding Cortex-M3/Thumb-2 architecture prototype. It is provided
for static inspection and development only.

The `core0`/`core1` directory names are retained from the legacy package-region
terminology. The SNC7320 is physically dual-core, while `0x10000000` is a
shared I-cache execution window. This prototype does not yet implement or prove
the second processor's reset/release and IPC startup. See
`../docs/SOC-DATASHEET-AUDIT-2026-08-18.md`.

The tree now includes independently authored implementations of the recovered
panel sequence, RGB controller protocol, Hall routing model and USB controller
stack. It still excludes vendor code/binaries, decompiler output, raw captures,
stock patch tooling, assigned USB identity and every generated binary.

This is public, inspection-oriented source. Do not commit locally built images,
stock inputs, captures, or proprietary analysis artifacts to this directory.

## Current status — 2026-08-23

All substantial software-owned functions supported by the available evidence
are implemented and host-tested, including five profiles, USB EP0/HID/vendor
transport, Hall/action processing, display/touch/RGB paths and atomic screen/
profile storage. Full-chip reads corrected the mutable store allow-list so it no
longer overlaps stock configuration or upload partitions.

The default build still parks before the application and leaves every
unverified peripheral, USB attachment and flash mutation path disabled. An
external ESP32-C3 full-stock restore/verification rehearsal has succeeded on the
physical unit, but the replacement images themselves have never run on the
board. Cold-start clock/OPI state, alternate-function pinmux and controller
electrical behavior remain hardware gates.

The two link images now carry fixed `KB7P` build-pair markers and use runtime
ABI v2. Standalone ELFs deliberately contain an erased all-`0xff` pair ID and
are not runnable images: the offline V1.22 planner must patch one derived ID
into both targets. Core0 validates the pair before USB attach, and the region-1
entry validates it again before data/BSS initialization or board I/O. The
linkers also reserve the CRC correction and sparse commit-gate blocks used by
the offline transaction model. This makes a checksum-compatible mixed build
fail-stop for external reset; it is not a proven transition back to USB ISP and
does not show that either paired image works on the board.

Requirements: GNU Make, Python 3, and `arm-none-eabi-gcc`/binutils.

```sh
make clean all
```

The build creates local, ignored ELF/disassembly files and checks that no
relocations remain. Header dependency files are generated automatically.

`make audit-profile` compiles feature paths while leaving board-verification and
flash-mutation gates closed. `make integration-check` additionally compiles
those gated branches. Neither touches a device or constitutes an installation
profile.

`make bundle` intentionally exits with an error. The offline-correctable audit
findings have regression-tested repairs, described in
`../docs/FIRMWARE-COMPLETION-2026-08-18.md`. USB/MCU2 identities and board
profiles, generic non-GPIO pinmux, logical-key→LED correlation and hardware
validation remain unresolved. External SPI is the demonstrated stock rollback
route. The repository has no supported USB flashing utility. Separate read-only
USB diagnostics, two fixed guarded destructive experiments that passed at
stock-loader scratch targets (including an observable exact 4-KiB footprint at
one target), and the proven external-SPI recovery notes live in
[`../tools/flash-access/`](../tools/flash-access/README.md); none is an
installation route for these ELFs. Do not install them.

The compatibility function named `kb7_enter_loader()` does not claim an
autonomous loader transition. The datasheet establishes that AIRCR/software
reset restarts PRAM, so the helper records the recovered request marker, disables
interrupts, and parks for an external reset. A proven ROM-entering watchdog,
remap, or external-reset path is still required. The recovery chord also
defaults off until GPIO pull/pinmux behavior and the chosen physical inputs are
validated.
