# KB7 Open Firmware — source-only research prototype

This repository contains independently authored, source-only interoperability
work for an unofficial KB7 firmware architecture and offline configuration
studio.

This is the public project repository. Treat every committed file as
immediately published: do not add stock firmware or flash dumps, vendor tools or
DLLs, decompiler output, captures, generated flash images, product artwork, or
other material that the project cannot redistribute.

**It is not yet board-validated firmware. Do not install it on hardware.** The
software-owned drivers and protocols are now implemented, but cold-start and
end-to-end board behavior still need physical validation. A stock
full-chip external-SPI restore has been rehearsed; that recovery result does not
validate the replacement image. Public defaults remain fail-closed and flash-
image generation is disabled.

## Current status — 2026-08-31

- The offline/software implementation is complete to the evidence currently
  available. `make check` passes 274 Python tests, browser validation, four ARM
  build profiles, hardware-fact checks and the public-tree safety audit.
- Two independent reads of the installed 32-MiB Macronix SPI NOR are
  bit-identical. They match the earlier USB-extracted V1.22 components and
  exposed stock-owned configuration/upload partitions that the custom storage
  map now preserves.
- An external ESP32-C3 SPI repair restored normal stock boot. The intermittent
  boot seen immediately afterward was consistent with the unpowered programmer
  remaining connected to the flash bus and disappeared when it was disconnected.
  The owner has since completed the full-chip restore/verification rehearsal and
  retained matching post-repair captures. External SPI is the demonstrated
  rollback path for this development unit.
- A read-only, hash-pinned audit now proves that stock V1.22, V1.24 and V1.33
  deliberately return to the preserved loader by writing its mailbox marker,
  running a relocation routine from SRAM, copying `0x10000` bytes from
  `0x60001000` to PRAM and only then requesting an AIRCR reset. AIRCR alone
  still restarts the current PRAM image and is not loader entry. An
  independently authored, default-off `recovery-proof` profile passes its
  offline byte, relocation, stack, vector and no-mutation checks, but has not
  run on hardware and does not yet establish a custom-firmware return to
  `10f5:5037`. See the
  [preserved-loader proof](docs/STOCK-LOADER-REENTRY-2026-08-23.md).
- A new fixed proof-campaign builder now turns that minimal Core-0 ELF plus two
  exact owner baselines into a private install-and-exact-stock-restore plan.
  Its stable proof target is checksum-valid custom Core 0 plus byte-exact stock
  Core 1; a single temporary Core-1 sector poison supplies the opposite-core
  barrier while Core 0 is rebuilt and is restored before the final Core-0
  commit. A separate one-operation executor has exhaustive offline
  state/transport fault coverage, no caller-selected flash fields, and pinned
  policy/source identities. The two owner baselines now independently rederive
  the exact 168-operation campaign ID
  `1ce62e95ee2c6c84b5abb8996f7964bacae661869152ead20f5c7138b2b0b508`,
  including exact proof-image and stock-restoration closure. The campaign's
  2026-08-24 preflight history includes an old stopped attempt and a later
  exact boundary-zero pass. A subsequent 2026-08-31 read-only preflight found
  two stable changed Core-1 bytes; external SPI independently reproduced them,
  after which a full SPI restore and separate readback returned the exact
  baseline and normal `10f5:5038` operation. A later full USB capture exposed
  a distinct command-aligned acquisition failure, including zero-filled and
  half-address pages. The legacy full-chip verifier returned status 0 despite
  failed CRCs, so it is not current pass/fail authority. The fixed
  baseline-aware short-read sweep passed on 2026-09-02 once the NOR lead stubs
  were removed, and the read-only preflight passed on 2026-09-03 under the
  post-image live-region policy on the separate preflight-only branch. Proof
  mutation remains locked here. The general paired-firmware executor remains
  locked and `flash_approved=false`. See the
  [fixed proof campaign](docs/LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md) and
  [read-reliability incident](docs/USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md).
- On 2026-09-05 the first hardware step changed to a region-1-only image
  with stock Core 0 kept in place. The
  [stock Core 0 to region-1 boot contract](docs/STOCK-CORE0-REGION1-CONTRACT-2026-09-05.md)
  is decoded and pinned by a read-only verifier, a 404-byte
  `region1-reentry-proof` sits at the stock application entry and re-enters
  the preserved loader, and a
  [40-operation single-sector patch campaign](docs/REGION1-REENTRY-CAMPAIGN-2026-09-05.md)
  is built and simulated offline, and the fixed executor on that branch is
  bound to it with both live gates false. It is unreviewed and has not run
  on hardware.
- The flash-access tooling adds proven external SPI recovery workflows,
  read-only USB-ISP diagnostics and fixed, dry-run-default USB mutation
  experiments. On 2026-08-23 one guarded V1.22 cycle at offset `0x0008e000`
  confirmed the sub-16-MiB `F6 18` + `F6 06` marker program and normal-NOR
  `F6 18` + `F6 15` erase sequence, with exact 32-MiB postflight comparisons
  and final restoration to the baseline. A second guarded test populated all
  4,096 bytes of sector `0x000c6000` plus immediate lower and upper guards. The
  target erase removed exactly the populated 4-KiB sector, both guards survived,
  every complete-array postimage matched, cleanup restored the baseline, and a
  later cold boot worked normally. That is a one-unit, one-loader, one-target
  observable footprint result; `F6 19` and general update safety remain unproven.
  This is not a supported general flasher; use SPI for owner-authorized
  ordinary, recovery and production writes.
- A new V1.22-only updater planner builds and checks an owner-local,
  manifest-preserving paired-region plan. It CRC-balances both replacement
  regions against the unchanged stock manifest, inserts a symmetric build-pair
  guard, invalidates both regions before dense staging, and commits core0 last.
  Its CLI has only offline `build` and `simulate` operations and reports
  `flash_approved=false`. A separate executor scaffold now provides only
  read-only live `preflight` and `reconcile`: it binds two exact full-chip reads,
  loader identity, USB topology and a durable journal, while its mutation path
  remains hard-disabled and unreachable from the CLI. Both read-only commands
  have now passed in separate live sessions at exact-stock boundary 0. A
  separate fixed two-sector scratch/restart experiment has also passed once.
  Its program and erase no-readback checkpoints were each classified from two
  exact full-chip reads in a new process without automatic replay; cleanup
  restored the baseline and the keyboard returned to normal `5038` operation.
  This proves command-complete host-session reconciliation at the fixed scratch
  addresses, not physical mid-command or power-loss recovery. A new, separate
  `kb7-updater-scratch-executor.py` expresses that same fixed scratch command
  set as 22 journal-derived, one-operation invocations. Its preceding v1 plan
  completed one hardware run on the development unit: all 18 programs and four
  erases reached exact whole-image boundaries, final new-process reconciliation
  cleared the journal at the byte-exact stock baseline, and a separate verifier
  entry point reproduced SHA-256
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`;
  the owner then reported normal keyboard operation. The historical v2 plan
  also completed one hardware run. At its mandatory `program-09` durable-
  intent checkpoint, the command and WIP-ready poll completed, then the process
  closed without postread or boundary advance and exited 4. A fresh process
  using the mutation-incapable verifier backend classified two full-chip reads
  as the exact boundary-10 postimage without retry. The remaining fixed plan
  restored the exact baseline, final reconciliation cleared state, a separate
  verifier reproduced the same 32-MiB hash with all three region CRCs valid,
  and the owner confirmed normal boot. The current v3 plan has also completed
  one hardware run. It moves the same mandatory checkpoint earlier: after the
  complete program CBW/data exchange and validated CSW, the process locally
  abandons USB,
  durably publishes and reads back `checkpoint_command_complete`, then self-
  terminates with signal 9/status 137 before WIP polling, postread, boundary
  publication or explicit USB close. The journal `fsync` means this tests
  durable command completion followed by host death, not immediate post-CSW
  death or known WIP activity. Preflight publishes `preflight_started`, and
  every step publishes raw intent, before constructing a backend or opening
  USB; either visible marker is terminal SPI. Only exact checkpoint-command-
  complete and final-complete states are reconcilable, and intermediate
  boundaries are not. Each read-only pass consumes a one-shot
  `*_reconcile_started` state before USB; transport, verification or close
  failure is terminal. Exact classification and strict close precede final
  publication; an exact target is accepted, while an unclassifiable atomic
  state change permits only fresh local `inspect`, never USB. Status 137
  is operator-observed—not journal-bound—and status 126 or ready-publication
  error permits cleanup only, invalidating the experiment even if boundary 10
  is observed. The observed run ended with status 137, an accidental second
  `step` was rejected before USB, local-only inspection confirmed the exact
  ready state, and fresh-process reconciliation accepted two exact postimage
  reads without replay. Cleanup restored the exact baseline, final
  reconciliation cleared state, the separate verifier reproduced all three
  region CRCs and the baseline hash, and the owner confirmed normal `5038`
  keyboard operation.
  Both executor and verifier reads use the same loader/SoC `F6 05`
  flash-controller path. This is not a physical command
  interruption or power cut, and no firmware region is touched. The
  harness cannot accept a firmware bundle or caller-selected mutation; the
  paired-firmware executor remains mutation-locked. None of these paths makes
  a custom-firmware hardware trial safe. See the
  [offline updater design](docs/USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md) and
  [executor scaffold status](docs/USB-UPDATER-EXECUTOR-SCAFFOLD-2026-08-23.md),
  plus the separate
  [fixed scratch executor status](docs/USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md),
  [v3 host-termination test plan](docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md),
  [v3 validation record](docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md),
  historical [v2 mandatory-checkpoint test plan](docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md),
  and [v2 validation record](docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).
- A detached Ed25519 authentication tool now revalidates the complete offline
  bundle before signing or verifying it and requires an explicitly pinned
  public-key fingerprint. This supplies a publisher-authentication mechanism,
  but no project release key or trust root is provisioned and a valid signature
  never changes `execution_authorized=false` or `flash_approved=false`. See the
  [offline authentication design](docs/OFFLINE-UPDATER-AUTHENTICATION-2026-08-23.md).
- No custom firmware has been installed. USB, display, touch, RGB, MCU2/Hall,
  cold-start memory setup and a legitimate USB identity still require board
  validation. The SNC and AT32 datasheets plus the complete stock static
  recovery now close the LCD mode-1, SPI0 mode-4 and P0.6 PWM pin-selection
  questions; see the
  [stock pinmux recovery](docs/STOCK-PINMUX-RECOVERY-2026-08-23.md). The
  remaining board plan is functional validation, not a search for a generic
  per-pad `SYS0_PINCTRL` encoding. `flash_approved` remains false.

See the [firmware completion status](docs/FIRMWARE-COMPLETION-2026-08-18.md),
[full-flash acquisition record](docs/FULL-FLASH-ACQUISITION-2026-08-22.md), and
[boot/recovery model](docs/BOOT-RECOVERY-MODEL.md) for the firmware evidence
boundaries. The
[stock loader-reentry audit and proof profile](docs/STOCK-LOADER-REENTRY-2026-08-23.md)
records the exact static result and its still-unrun hardware gate. The
[fixed proof campaign and runbook](docs/LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md)
records the owner-bound, independently reverified offline installer/restorer
and its separate live-enable lock. The
[region-1 boot contract](docs/STOCK-CORE0-REGION1-CONTRACT-2026-09-05.md) and
[region-1 patch campaign](docs/REGION1-REENTRY-CAMPAIGN-2026-09-05.md) record
the 2026-09-05 pivot that keeps stock Core 0 installed, and the
[region-1 runbook](docs/REGION1-REENTRY-RUNBOOK-2026-09-05.md) the gated
revisions and hardware sequence that must follow. The
[bounded USB-ISP validation record](docs/USB-ISP-WRITE-VALIDATION-2026-08-23.md),
[guarded erase-footprint result](docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md),
[flash-access guide](tools/flash-access/README.md), and
[F6 erase analysis](tools/flash-access/F6-ERASE-ENCODING.md) record the separate
stock-recovery investigation. The
[erase-footprint test plan](tools/flash-access/ERASE-GRANULARITY-TEST-PLAN.md)
records the completed fixed hardware experiment and its recovery boundary; the
[scratch restart validation](docs/USB-ISP-SCRATCH-RESTART-VALIDATION-2026-08-23.md)
and [test plan](tools/flash-access/SCRATCH-RESTART-TEST-PLAN.md) record the
completed process/session-restart experiment and its stricter limits. The
[fixed scratch executor plan](docs/USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md)
and its
[completed hardware validation](docs/USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md)
record the current control harness and the exact limits of its historical v1
development-unit run. The
[mandatory active-intent test plan](docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
and [v2 validation record](docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md)
record the historical checkpoint sequence, observed result and its narrower
proof boundary. The current
[v3 host-termination plan](docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md)
and [v3 validation record](docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md)
record the durable-command-complete/pre-WIP sequence, its completed one-unit
result and stricter stop rules.

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
  verification tools, F6 command analysis and fixed guarded USB write-path
  experiments, plus a V1.22 updater planner/checker, read-only firmware
  executor scaffold, separate fixed scratch-only executor, and a fixed,
  owner-campaign-bound
  fixed loader-reentry proof campaign. It contains no stock bytes and no
  supported or general USB firmware flasher.
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
make -C replacement_fw recovery-proof
```

The default, guarded audit, and all-branches integration profiles create ignored
ELF/disassembly files for local inspection. `integration-check` compiles board-
verified branches but is not evidence that a board passed those gates. The
`recovery-proof` target creates a planner-compatible, immediate-loader-reentry
ELF and verifies its minimal linked form; it neither makes that ELF
checksum-compatible by itself nor emits a bundle or touches hardware. `make
bundle` deliberately fails: no installable package can be produced by that
target. The fixed loader-reentry campaign builder can balance this exact proof
ELF against two exact owner baselines, but emits only private,
execution-unapproved sector payloads and model metadata. Its separate executor
pins the exact reviewed owner campaign ID, but both its USB preflight and
mutation paths are hard-disabled in the CLI, the live entry points and both
USB backends. The fixed short-chunk read-reliability gate passed on
2026-09-02 once the NOR lead stubs were removed; re-enabling even the
read-only preflight remains a separate reviewed revision.

## Public-repository boundary

Read [OPEN-SOURCE-REVIEW.md](docs/OPEN-SOURCE-REVIEW.md) before contributing or
making a release, and
[SECURITY-AUDIT-2026-08-17.md](docs/SECURITY-AUDIT-2026-08-17.md) before changing
hardware-facing code. Then review
[AUDIT-REMEDIATION-2026-08-17.md](docs/AUDIT-REMEDIATION-2026-08-17.md) and the
later [firmware completion status](docs/FIRMWARE-COMPLETION-2026-08-18.md),
[SNC7320 datasheet audit](docs/SOC-DATASHEET-AUDIT-2026-08-18.md), and
[boot/recovery model](docs/BOOT-RECOVERY-MODEL.md), including the later
[stock loader-reentry proof](docs/STOCK-LOADER-REENTRY-2026-08-23.md). The
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
