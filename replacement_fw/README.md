# Replacement firmware source

This is a freestanding Cortex-M4/Thumb-2 architecture prototype. It is provided
for static inspection and development only.

The public export intentionally omits the privately recovered panel profile,
RGB topology, captured key-selector map, USB identity/controller bring-up, stock
patch tooling, and every generated binary. The corresponding LCD, RGB, and USB
drivers fail closed.

Requirements: GNU Make, Python 3, and `arm-none-eabi-gcc`/binutils.

```sh
make clean all
```

The build creates local, ignored ELF/disassembly files and checks that no
relocations remain. Header dependency files are generated automatically.

`make bundle` intentionally exits with an error. The source has unresolved
clock, vector, MCU2, mapping, timeout, storage, parser, and UI correctness
findings described in `../docs/SECURITY-AUDIT-2026-08-17.md`. Do not convert its
ELFs into device images or install them on hardware.
