# KB7 Open Firmware — source-only research prototype

This repository contains independently authored, source-only interoperability
work for an unofficial KB7 firmware architecture and offline configuration
studio.

This is the public project repository. Treat every committed file as
immediately published: do not add stock firmware or flash dumps, vendor tools or
DLLs, decompiler output, captures, generated flash images, product artwork, or
other material that the project cannot redistribute.

**It is not yet board-validated firmware. Do not install it on hardware.** The
software-owned drivers and protocols are now implemented, but several
electrical/pinmux/controller assumptions and a repeatable full rollback
procedure still need physical proof. Public defaults remain fail-closed and
flash-image generation is disabled.

## Current status — 2026-08-22

- The offline/software implementation is complete to the evidence currently
  available. `make check` passes 90 Python/C integration tests, browser
  validation, three ARM build profiles, hardware-fact checks and the public-tree
  safety audit.
- Two independent reads of the installed 32-MiB Macronix SPI NOR are
  bit-identical. They match the earlier USB-extracted V1.22 components and
  exposed stock-owned configuration/upload partitions that the custom storage
  map now preserves.
- An external ESP32-C3 SPI repair restored normal stock boot. The intermittent
  boot seen immediately afterward was consistent with the unpowered programmer
  remaining connected to the flash bus and disappeared when it was disconnected.
  This is a demonstrated emergency-repair path, not yet a repeatable,
  byte-identical full-chip rollback qualification.
- The flash-access tooling adds proven external SPI recovery workflows
  and read-only USB-ISP diagnostics. The loader's `F6 06` program layout was
  established by a destructive incident; the `F6 15`/`F6 19` erase layouts are
  resolved by calibrated static analysis but remain untested on hardware. The
  USB tooling intentionally cannot mutate flash; use SPI for owner-authorized
  repair writes.
- No custom firmware has been installed. USB, display, touch, RGB, MCU2/Hall,
  pinmux, cold-start memory setup and a legitimate USB identity still require
  board validation. `flash_approved` remains false.

See the [firmware completion status](docs/FIRMWARE-COMPLETION-2026-08-18.md),
[full-flash acquisition record](docs/FULL-FLASH-ACQUISITION-2026-08-22.md), and
[boot/recovery model](docs/BOOT-RECOVERY-MODEL.md) for the firmware evidence
boundaries. The [flash-access guide](tools/flash-access/README.md) and
[F6 erase analysis](tools/flash-access/F6-ERASE-ENCODING.md) record the separate
stock-recovery investigation.

## Repository contents

- `replacement_fw/` — freestanding Cortex-M3 source with platform boot, USB,
  LCD/touch/RGB, Hall input, HID/gamepad, persistent profile/screen storage and
  recovery diagnostics. Hardware-sensitive paths require explicit gates.
- `pc_app/` — dependency-free browser editor plus Python validators, compiler,
  protocol model, storage model, samples, and tests. It performs no device I/O.
- `hardware/` — page-cited, machine-readable SoC/MMIO/IRQ/DMA, KB7 package-pin,
  reset and full-flash observations, with explicit evidence boundaries.
- `docs/` — project-owned screen/profile/control/storage formats, the full
  security audit, remediation matrix, report schemas, and public-source
  provenance review.
- `tools/inspect_stock_flash.py` — read-only inspection of an owner-supplied
  32-MiB dump; raw images and reports remain outside the repository.
- `tools/flash-access/` — ESP32/`flashrom` recovery notes, read-only USB-ISP
  verification tools and the F6 command analysis. It contains no stock bytes
  and no USB write utility.
- `tools/check_public_tree.py` — rejects compiled/vendor artifacts, archive and
  executable formats, symlinks, build directories, and prohibited artifact
  filenames.

Reverse-engineering inputs, vendor firmware, decompiler output, captures,
stock-patch experiments, and generated images are not part of this public
repository. The implementations here are independently authored from recovered
interoperability facts and published datasheet facts.

## Try the studio

Open `pc_app/web/index.html` in a modern browser. It has display, keyboard RGB,
Hall-switch actuation, Rapid Trigger, and analog-axis design workspaces. These
are offline simulations and profile editors; they do not claim live device
control.

Run its tests with:

```sh
make check
```

That root target runs the studio tests plus the firmware builds and public-tree
checks. The narrower Python and JavaScript commands remain documented in
`pc_app/README.md`.

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

## Public-repository boundary

Read [OPEN-SOURCE-REVIEW.md](docs/OPEN-SOURCE-REVIEW.md) before contributing or
making a release, and
[SECURITY-AUDIT-2026-08-17.md](docs/SECURITY-AUDIT-2026-08-17.md) before changing
hardware-facing code. Then review
[AUDIT-REMEDIATION-2026-08-17.md](docs/AUDIT-REMEDIATION-2026-08-17.md) and the
later [firmware completion status](docs/FIRMWARE-COMPLETION-2026-08-18.md),
[SNC7320 datasheet audit](docs/SOC-DATASHEET-AUDIT-2026-08-18.md), and
[boot/recovery model](docs/BOOT-RECOVERY-MODEL.md). The
[full-flash acquisition record](docs/FULL-FLASH-ACQUISITION-2026-08-22.md)
supersedes all earlier assumptions that the erased flash tail was generally
available for custom storage. Run this immediately before every commit or
release:

```sh
python3 tools/check_public_tree.py .
python3 tools/audit_firmware_source.py .
```

This repository is already public. Never add files from outside this repository,
a device dump, a proprietary analysis input, or a locally generated firmware
package. Review both the staged diff and newly introduced history before every
push.

## License and trademarks

Repository-owned source and documentation are licensed under Apache-2.0; see
`LICENSE`. `NOTICE` identifies the independent-project and trademark boundary.
No license is granted to third-party firmware, marks, or assets.
