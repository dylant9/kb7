# KB7 Open Firmware — source-only research prototype

This repository contains independently authored, source-only interoperability
work for an unofficial KB7 firmware architecture and offline configuration
studio.

**It is not flash-ready firmware. Do not install it on hardware.** The current
firmware has known correctness and recovery blockers, and the public export
intentionally omits device-specific panel, RGB, USB, and key-selector data.
Flash-image generation is disabled.

## Repository contents

- `replacement_fw/` — freestanding Cortex-M4 source that can be compiled to ELF
  files for static inspection. Hardware-sensitive public drivers fail closed.
- `pc_app/` — dependency-free browser editor plus Python validators, compiler,
  protocol model, storage model, samples, and tests. It performs no device I/O.
- `docs/` — project-owned screen/profile/control/storage formats, the full
  security audit, and the public-source provenance review.
- `tools/check_public_tree.py` — rejects compiled/vendor artifacts, archive and
  executable formats, symlinks, build directories, and known private filenames.

The private reverse-engineering evidence, vendor firmware, decompiler output,
captures, stock-patch experiments, and generated images are not part of this
repository and are not required to run the offline studio.

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
```

This creates ignored ELF/disassembly files for local inspection. `make bundle`
deliberately fails: no flash image can be produced from the public tree.

## Publication boundary

Read [OPEN-SOURCE-REVIEW.md](docs/OPEN-SOURCE-REVIEW.md) before publication and
[SECURITY-AUDIT-2026-08-17.md](docs/SECURITY-AUDIT-2026-08-17.md) before changing
any hardware-facing code. Run this immediately before every commit or release:

```sh
python3 tools/check_public_tree.py .
```

Only this repository directory is intended for publication. Never add files
from its parent workspace or from a device dump.

## License and trademarks

Repository-owned source and documentation are licensed under Apache-2.0; see
`LICENSE`. `NOTICE` identifies the independent-project and trademark boundary.
No license is granted to third-party firmware, marks, or assets.
