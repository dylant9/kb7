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
recovery validation remain unresolved. Do not install these ELFs.

The compatibility function named `kb7_enter_loader()` does not claim an
autonomous loader transition. The datasheet establishes that AIRCR/software
reset restarts PRAM, so the helper records the recovered request marker, disables
interrupts, and parks for an external reset. A proven ROM-entering watchdog,
remap, or external-reset path is still required. The recovery chord also
defaults off until GPIO pull/pinmux behavior and the chosen physical inputs are
validated.
