# KB7 Open Firmware — source-only research prototype

This repository contains independently authored, source-only interoperability
work for an unofficial KB7 firmware architecture and offline configuration
studio.

**It is not yet board-validated firmware. Do not install it on hardware.** The
software-owned drivers and protocols are now implemented, but several
electrical/pinmux/controller assumptions and the recovery procedure still need
physical proof. Public defaults remain fail-closed and flash-image generation
is disabled.

## Repository contents

- `replacement_fw/` — freestanding Cortex-M3 source with platform boot, USB,
  LCD/touch/RGB, Hall input, HID/gamepad, persistent profile/screen storage and
  recovery diagnostics. Hardware-sensitive paths require explicit gates.
- `pc_app/` — dependency-free browser editor plus Python validators, compiler,
  protocol model, storage model, samples, and tests. It performs no device I/O.
- `hardware/` — page-cited, machine-readable SoC/MMIO/IRQ/DMA and KB7 package
  pin facts, with explicit confidence and continuity status.
- `docs/` — project-owned screen/profile/control/storage formats, the full
  security audit, remediation matrix, report schemas, and public-source
  provenance review.
- `tools/check_public_tree.py` — rejects compiled/vendor artifacts, archive and
  executable formats, symlinks, build directories, and known private filenames.

The private reverse-engineering evidence, vendor firmware, decompiler output,
captures, stock-patch experiments, and generated images are not part of this
repository. The implementations here are independently authored from recovered
interoperability facts and published datasheet facts.

## Try the studio

Open `pc_app/web/index.html` in a modern browser. It has display, keyboard RGB,
Hall-switch actuation, Rapid Trigger, and analog-axis design workspaces. These
are offline simulations and profile editors; they do not claim live device
control.

Run its tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pc_app python3 -m unittest discover -s pc_app/tests -v
node --check pc_app/web/app.js
```

## Inspect the firmware source

With GNU Make and an `arm-none-eabi` GCC/binutils toolchain:

```sh
make -C replacement_fw clean all
make -C replacement_fw audit-profile
make -C replacement_fw integration-check
```

The default, guarded audit, and all-branches integration profiles create ignored
ELF/disassembly files for local inspection. `integration-check` compiles board-
verified branches but is not evidence that a board passed those gates. `make
bundle` deliberately fails: no flash image can be produced by that target.

## Publication boundary

Read [OPEN-SOURCE-REVIEW.md](docs/OPEN-SOURCE-REVIEW.md) before publication and
[SECURITY-AUDIT-2026-08-17.md](docs/SECURITY-AUDIT-2026-08-17.md) before changing
any hardware-facing code, then review
[AUDIT-REMEDIATION-2026-08-17.md](docs/AUDIT-REMEDIATION-2026-08-17.md) and the
later [firmware completion status](docs/FIRMWARE-COMPLETION-2026-08-18.md),
[SNC7320 datasheet audit](docs/SOC-DATASHEET-AUDIT-2026-08-18.md), and
[boot/recovery model](docs/BOOT-RECOVERY-MODEL.md). Run
this immediately before every commit or release:

```sh
python3 tools/check_public_tree.py .
python3 tools/audit_firmware_source.py .
```

Only this repository directory is intended for publication. Never add files
from its parent workspace or from a device dump.

## License and trademarks

Repository-owned source and documentation are licensed under Apache-2.0; see
`LICENSE`. `NOTICE` identifies the independent-project and trademark boundary.
No license is granted to third-party firmware, marks, or assets.
