# Replacement firmware source

This is a freestanding Cortex-M3/Thumb-2 architecture prototype. It is provided
for static inspection and development only.

The `core0`/`core1` directory names are retained from the legacy package-region
terminology. The SNC7320 is physically dual-core, while `0x10000000` is a
shared I-cache execution window. This prototype does not yet implement or prove
the second processor's reset/release and IPC startup. See
`../docs/SOC-DATASHEET-AUDIT-2026-08-18.md`.

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

`make audit-profile` also compiles and links every guarded code path with all
hardware feature gates set, without producing a flash image or touching a
device. This is a compile-time audit profile, not an installation profile.

`make bundle` intentionally exits with an error. The offline-correctable audit
findings have regression-tested repairs, described in
`../docs/AUDIT-REMEDIATION-2026-08-17.md`. USB enumeration, board profiles,
physical selector mapping, NOR mutation, and hardware recovery validation remain
unresolved. Do not convert these ELFs into device images or install them.
