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
board. Cold-start clock/OPI state and controller electrical/end-to-end behavior
remain hardware gates. LCD mode 1, MCU2 SPI0 mode 4 and P0.6 PWM pin selection
are now statically recovered from both datasheets and three stock releases.

The two link images now carry fixed `KB7P` build-pair markers and use runtime
ABI v2. Standalone ELFs deliberately contain an erased all-`0xff` pair ID and
are not runnable images: the offline V1.22 planner must patch one derived ID
into both targets. Core0 validates the pair before USB attach, and the region-1
entry validates it again before data/BSS initialization or board I/O. The
linkers also reserve the CRC correction and sparse commit-gate blocks used by
the offline transaction model. These ELFs are planner-compatible, not
checksum-compatible images by themselves: the separate planner must derive and
apply the pair ID, checksum correction and commit gate. Its symmetric pair
guard makes a mixed planned pair fail-stop for external reset; it does not show
that either paired image works on the board.

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

`make recovery-proof` builds a deliberately minimal, planner-compatible Core-0
ELF that takes the independently authored preserved-loader route before
`core0_main()`. The target verifies the exact 84-byte stackless relocation
bridge, 72-byte loader-copy blob, their hashes and relocation-free code, the
stack reserve, reset/vector shape, and absence of application, USB-init,
C-copy and flash-mutation symbols. It does not CRC-balance the ELF, emit a
bundle, open a device, or establish hardware behavior. The stock route is
statically proved
across V1.22, V1.24 and V1.33; the custom proof remains default-off and has not
run on hardware. See
[`../docs/STOCK-LOADER-REENTRY-2026-08-23.md`](../docs/STOCK-LOADER-REENTRY-2026-08-23.md).
The separate
[`fixed proof campaign`](../docs/LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md)
can balance this exact Core-0 ELF while retaining stock Core 1 and derive an
exact-stock reverse plan. The supplied owner baselines now reproduce the pinned
168-operation campaign ID and exact proof/stock closures. Its source/policy
gates pass offline, and the independent fixed executor is now enabled only for
that bounded owner campaign. The proof remains hardware-unrun.

`make bundle` intentionally exits with an error. The offline-correctable audit
findings have regression-tested repairs, described in
`../docs/FIRMWARE-COMPLETION-2026-08-18.md`. USB/MCU2 identities and board
profiles, logical-key→LED correlation and hardware
validation remain unresolved. External SPI is the demonstrated stock rollback
route. The repository has no supported USB flashing utility. Separate read-only
USB diagnostics, two fixed guarded destructive experiments that passed at
stock-loader scratch targets (including an observable exact 4-KiB footprint at
one target), a read-only updater preflight/reconciliation scaffold, and the
proven external-SPI recovery notes live in
[`../tools/flash-access/`](../tools/flash-access/README.md); none is an
authorized installation route for these ELFs. Do not install them.

The compatibility function named `kb7_enter_loader()` remains fail-closed in
ordinary builds: it records and reads back the request marker, disables
interrupts, and parks. With the separate unverified loader-reentry gate enabled,
it instead reproduces the stock sequence by relocating the preserved loader
into PRAM from SRAM before AIRCR reset. A marker plus AIRCR alone is still a
false route because software reset restarts whatever is already in PRAM. The
custom sequence and the recovery chord both remain default-off until their
dedicated hardware validations pass; external SPI remains the final fallback.
