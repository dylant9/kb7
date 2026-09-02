# KB7 flash access tooling

Two independent paths to the KB7's SPI-NOR (Macronix MX25L25645G, 32 MB), plus
the diagnostics used to characterise them.

This directory is part of the public, source-only repository. It contains no
stock dump, repair image, vendor binary, or extracted firmware. Supply only
images obtained lawfully from hardware you own, keep them outside the
repository, and verify them independently before any write. None of these tools
makes the replacement firmware flash-approved.

| Path | Transport | Reliability | Can write? |
|---|---|---|---|
| **SPI** | ESP32-C3 running `serprog` + `flashrom` | Proven, byte-exact | **Yes — proven** |
| **USB ISP** | Bootloader mass-storage `F6` commands | Reads, fixed marker/erase cycles and fixed scratch restart/executor cycles passed on one V1.22 unit | **Narrow lab primitives validated; not a supported flasher** |

---

## ⚠️ Read this first: the flash-bus lead hazards

Two distinct harness hazards corrupt the SoC's own reads of the NOR while
flashrom reads over the same leads at 1-4 MHz stay perfectly clean. Both were
found on the development unit; both are avoidable.

### 1. Never leave the ESP32 wired to the flash bus while it is powered off

An unpowered CMOS input clamps any signal driven above ~0.7 V through its
ESD protection diode into the dead VCC rail. With the ESP32 attached-but-off,
every SoC flash read fought four parasitic diodes hanging off CS/CLK/MOSI/MISO.

Observed consequences, all of which vanished the moment the ESP32 was unplugged:

* intermittent boot failures (the loader CRC-checks 21 MB of region 2 on every
  boot; one glitched byte drops it to ISP mode)
* a corrupted LCD image (core1, including the display driver, is loaded from
  that same flash)
* an apparent ~0.3 % per-command error rate on USB ISP reads — which
  disappeared completely, 1200/1200 commands clean, once disconnected

Either **power the programmer** or **physically disconnect it**. Wired-and-dead
is one state to avoid.

### 2. Never leave long lead stubs on the bus, even with the programmer removed

The SoC's XIP flash controller clocks the NOR far faster than flashrom drives
the leads. A ~300 mm unterminated stub soldered to CS/CLK/DI/DO reflects those
edges. On 2026-09-02 the fixed read-reliability sweep failed 14 of 400 reads
with the programmer physically detached and the stubs still attached, then
passed 400 of 400 after the stubs were cut to ~20 mm and insulated
([record](../../docs/USB-ISP-READ-RELIABILITY-VALIDATION-2026-09-02.md)). The
failure signature is per command, typically a whole command zero-filled or
served from exactly half its requested address, which is a lost clock in the
SPI address phase at the SoC-NOR interface, not a USB or NOR-content fault.

Rules: keep any permanent leads at ~20 mm or less with an inline connector or
jumper at the NOR end; power the programmer or physically disconnect it; and
treat "programmer disconnected" as insufficient by itself.

---

## Hardware: ESP32-C3 as a serprog programmer

Firmware: [`thisiseth/esp32-serprog`](https://github.com/thisiseth/esp32-serprog)
built with ESP-IDF ≥ 6.0. Upstream's default pins for non-classic targets are
GPIO 40/41/42, which **do not exist on the ESP32-C3** (GPIO0–21 only) — they are
ESP32-S3 pins. Use a C3-specific branch. Strapping pins GPIO2/8/9 are avoided
because an attached flash chip can drive them at reset and force download mode.

| Flash pin | Signal | XIAO pad | GPIO |
|---|---|---|---|
| 1 | CS# | D5 | 7 |
| 2 | DO (MISO) | D2 | 4 |
| 4 | GND | GND | — |
| 5 | DI (MOSI) | D3 | 5 |
| 6 | CLK | D4 | 6 |

Pins 3 (WP#), 7 (HOLD#) and 8 (VCC) are supplied by the board — power the
keyboard for the flash rail and hold the SoC in reset via the RST line so it
stays off the bus. Confirm with `lsusb | grep 10f5`: only `503d` (the hub)
should be present.

**Speed:** 1–4 MHz works reliably over flying leads; 16 MHz fails to probe.
That ceiling is set by the wiring, not the chip — the SoC reads the same part
far faster over PCB traces.

---

## USB device modes

| VID:PID | Meaning |
|---|---|
| `10f5:503d` | CH334F internal hub (always present) |
| `10f5:5038` | Keyboard running normally |
| `10f5:5037` | Bootloader / ISP mode (USB mass storage) |

`kb7-enter-isp.py` switches a running keyboard into ISP mode by sending a vendor
HID feature report to the interface exposing usage page `0xFF90`. Volatile — a
power-cycle restores normal operation.

---

## Verified `F6` command encodings

The bootloader identifies itself as `v0.001 test!` (via `F6 F1`) and its bulk-IN
endpoint fails above 4 KB per transfer, so keep reads at ≤ 0x1000.

### Confirmed on hardware

| Cmd | Function | Encoding |
|---|---|---|
| `F6 00` | Identify | 2 bytes, exactly `01 01` |
| `F6 01` | Read status | 1 byte; bit 0 = WIP |
| `F6 05` | **NOR read** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 06` | **NOR program** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset in the official path); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 17` | Enter 4-byte addressing | no operands |
| `F6 18` | Leave 4-byte addressing for a sub-16-MiB operation | no operands |
| `F6 15` | Normal-NOR erase at the tested target | `CDB[3:5]` = BE16 512-byte-block index; no count |
| `F6 F1` | Device descriptor | 36 bytes |

The V1.22 loader has one confirmed Bulk-Only Transport quirk: for every `F6`
command it leaves CSW `dCSWDataResidue` equal to the requested CBW data length,
even after completing an exact data phase. The tools check this exact value per
command (for example 2 for `F6 00`, 4096 for a 4-KiB `F6 05`, and 0 for a
no-data command). They do not generally permit nonzero or arbitrary residue.

`F6 F1` transfers 36 bytes, but the V1.22 handler explicitly initializes only
bytes 0–27 and 32–35; bytes 28–31 are an uninitialized stack tail included by
its final fixed-size copy. The tools require the exact stable version, device
and magic fields and exclude only that four-byte tail from state hashes. They
still require the complete 36-byte USB transfer.

Static tracing of the vendor orchestration additionally establishes that it
selects `F6 17` when the program or erase range crosses the absolute
`0x61000000` boundary, and `F6 18` (no operands) when the range remains below
it. The 2026-08-23 validation cycle exercised `F6 18` immediately before both
the sub-16-MiB program and erase.

### Erase encoding: static proof plus bounded hardware validation

Calibrated data-flow analysis of the updater proved:

| Cmd | Function | Encoding |
|---|---|---|
| `F6 15` | 4-KiB-path erase | `CDB[3:5]` = BE16 of `(aligned_address >> 9) & 0xffff`; no count |
| `F6 19` | alternate 128-KiB-path erase | `CDB[3:7]` = BE32 of `aligned_address >> 9`; no count |

The erase field is a **512-byte-block index**, unlike read/program. The
shifted value was traced into the builder's address argument and then into the
CDB bytes. A complete companion-SDK review also confirmed that both available
SCSI submission paths copy that 16-byte CDB unchanged and that no lower layer
rescales its fields. See [F6-ERASE-ENCODING.md](F6-ERASE-ENCODING.md) for the
complete proof and [F6-WRITE-ENCODING.md](F6-WRITE-ENCODING.md) for the final
command summary.

`F6 19` is not the automatic “above 16 MiB” form. A separate internal
flash-type selector chooses that path. For both program and erase, the updater
emits `F6 17` when the NOR operation range crosses `0x61000000` and `F6 18`
otherwise. This address-mode choice neither changes the interpretation of the
`F6 15` block index nor reads or modifies the flash-type selector. Normal KB7
NOR erase therefore remains `F6 15` in either address mode. A 16-bit index in
512-byte units covers the entire 32-MiB chip.

On 2026-08-23 the V1.22 preserved loader accepted `F6 15` with block index
`0x0470` after `F6 18` and removed a previously verified marker at flash offset
`0x0008e000`. The complete 32-MiB post-image compared byte-for-byte equal to the
original baseline. That confirms the normal-NOR target interpretation on this
unit; it does not prove exact erase granularity because the rest of the sector
and surrounding gap were already `0xff`. `F6 19` remains untested.

The fixed follow-up `kb7-isp-erase-granularity.py` subsequently populated every
byte of sector `0x000c6000`, placed non-`0xff` guards immediately below and
above it, and required the whole
aligned `[0x000c0000,0x00100000)` containment envelope to be erased in the
baseline. It additionally pins the actual preserved-loader flash window
`[0x00001000,0x00010000)` to SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`
in the offline baseline, every live full-chip preflight and the saved state; USB
identify replies alone are not accepted as proof of the executing loader code.
Its plan hash also binds the literal ten `F6 06` and three `F6 15` CDBs, the
`F6 18` mode subcode, flash/block/sector sizes, payload hashes, geometry, and
SHA-256 of the experiment, strict writer and verifier source files. With the
reviewed source tree that fixed plan hash is
`a68642a348b18ee27a2f1cfdb6c8137aeff43c0ce14487f9c765c4c76e9be783`;
source or command drift changes it and invalidates prior stage state. This is a
fail-closed consistency check, not code signing.
It is dry-run by default and has four identity- and image-bound stages: prepare,
erase the target, clean the lower guard, and clean the upper guard back to the
exact baseline. That fixed cycle passed on the development unit: all 4,096
target bytes erased, both adjacent guards survived exactly, every 32-MiB
postimage matched its prediction, cleanup restored the baseline, and the owner
then confirmed a working cold boot. This proves an observable exact 4-KiB
footprint only at that target with this unit and loader. See the
[runbook](ERASE-GRANULARITY-TEST-PLAN.md) and
[dated result](../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md).

### The disproven Phase-0 program model

An earlier model treated `F6 06` as taking a **scaled** address
(`aligned_offset >> 9`) and a **byte** count. Both assumptions were wrong, as
established destructively:

> Sent `f6 06 00 00 00 04 70 01 00 …` intending "program 256 bytes at
> `0x8e000`" (scaled index `0x470`, byte count `0x0100`).
> The device wrote **128 KB starting at byte address `0x470`**.
> Damage spanned `0x470`–`0x2046f`; last changed byte `0x2046f` = `0x470 +
> 0x20000` exactly.

So `F6 06` takes:
* a **raw byte address** — the same encoding as `F6 05`, *not* a scaled index
* a count in **512-byte blocks** — `0x0100` meant 256 × 512 = 128 KB

This overwrote the header, bootloader, manifest and core0. Recovery required a
full-chip rewrite over SPI.

The re-analysis first reproduced that known result from the updater before applying
the same argument trace to erase. In the program path the `>> 9` is applied to
the transfer **size**; in the erase path it is applied to the aligned
**address**.

### ⚠️ Bounded USB mutations validated — not a supported flashing path

**If you have found this repository and want to flash a KB7: use the SPI path.**
The narrow marker cycle and fixed erase-footprint cycle have passed under
laboratory guards; no supported or general USB firmware updater exists. The
offline planner described below cannot touch a device, and the paired-firmware
executor scaffold can only preflight and reconcile through read-only full-chip
captures. A separate dry-run-default scratch executor can replay only 22 fixed
non-firmware operations. Its preceding v1 plan completed once on the development
unit and restored the byte-exact baseline. The historical v2 plan's mandatory
WIP-ready/no-postread active-intent checkpoint also passed once, reconciled its
  exact postimage in a fresh read-only process, restored the baseline and returned
  to normal operation. The current v3 plan has also completed once: after
  validated program CSW it locally abandons USB, durably publishes and reads back
`checkpoint_command_complete`, then self-terminates with signal 9/status 137
  before WIP polling, postread or explicit USB close. Fresh-process
  reconciliation accepted the exact postimage without replay, cleanup restored
  the baseline, and normal `5038` keyboard operation returned. This remains
  bounded laboratory evidence, not a general update path.
Treat anything here that writes over USB as experimental and capable of
destroying your bootloader.

Host-side address validation **cannot** protect against device-side
misaddressing. An earlier host tool correctly refused intended targets outside
the scratch window — but the device acted on the *encoded* value (`0x470`), not
the intended offset (`0x8e000`), and overwrote the header, bootloader, manifest
and core0. Recovery required a full-chip SPI rewrite.

`kb7-isp-write2.py` settled the loader-side `F6 15` question for one V1.22 unit,
target and command size. Its exact reviewed sequence passed once. It remains
**dry-run by default**, derives an unused scratch sector from the connected
manifest, requires exact full-chip pre/post images, and refuses to erase unless
a separately verified program stage left its bound marker and authorization
state. It is a restricted validation experiment, not a flashing tool. See
[WRITE-TEST-PLAN.md](WRITE-TEST-PLAN.md) before considering its explicit
`--commit` mode.

The separate `kb7-isp-erase-granularity.py` does not broaden that primitive
into a flasher. Its address, patterns, geometry and commands are fixed solely to
make an under- or over-erase observable at one guarded target. Its completed
hardware pass proved that observable exact 4-KiB footprint for the tested V1.22
loader, unit and target. It did not prove `F6 19`, arbitrary update planning or
power-loss recovery, and the fixed script remains destructive and unsuitable
as an updater.

The successful cycle does not make another mutation intrinsically safe:
transport failure, power loss, an untested offset/version or a future tooling
defect can still damage the boot chain. The loader is an early `v0.001 test!`
build and its USB bulk path has other observed limitations.

**Do not attempt a USB write without a working SPI programmer, a byte-exact
backup of your own device, and a willingness to spend 30 minutes restoring it.**

---

## Tools

### SPI path (flashrom + ESP32)

| Script | Purpose |
|---|---|
| `kb7-read-1m.sh` / `-4m` / `-8m` / `-16m` | Full-chip read at a given SPI clock; requires an output path and optionally checks a caller-supplied SHA-256 |
| `kb7-compare.sh <dumpA> <dumpB>` | Diff two caller-supplied dumps: clusters differences, reports bit-flip direction, and checks all three region CRCs |
| `kb7-repair-layout.txt` | flashrom layout confining a write to `0x00a00000-0x00a0ffff`, keeping the bootloader outside the written region |

Incident-specific surgical restore example (only the named region is touched):

```sh
flashrom -p serprog:dev=/dev/ttyACM0:921600,spispeed=1M \
  -c "MX25L25635F/MX25L25645G" \
  -l kb7-repair-layout.txt -i repair -w <image>.bin --progress
```

`<image>.bin` must be a verified, owner-supplied full-chip image whose bytes for
that exact repair region are known-good; this is not a generic custom-firmware
installation command. Keep the SoC in reset, verify 3.3-V signalling, and retain
two matching backups before writing. Flashrom verifies the **whole chip** by
default after writing; add `-N` to verify only the written region.

### USB ISP path

| Script | Purpose | Safety |
|---|---|---|
| `kb7-enter-isp.py` | Switch a running keyboard into ISP mode | volatile; asks before sending |
| `kb7-isp-verify.py` | Historical full-chip read/CRC diagnostic through the SoC controller | **read-only, but not current pass/fail authority: legacy CRC failure exits 0** |
| `kb7-isp-repeat.py` | Fixed baseline-aware sweep of five pinned ranges at 512/1024/2048/4096-byte command sizes | **read-only; dry-run default; failed 14 of 400 reads with 300 mm NOR lead stubs, passed 400/400 after removing them (2026-09-02)** |
| `kb7-isp-write2.py` | Two-stage marker-program/sector-erase validation experiment | **destructive; dry-run by default; not a firmware flasher** |
| `kb7-isp-erase-granularity.py` | Fixed four-stage guarded test of the observable `F6 15` erase footprint | **destructive; dry-run by default; passed once at the fixed target** |
| `kb7-isp-scratch-restart.py` | Fixed two-sector experiment with two deliberate no-readback/reconciliation checkpoints | **destructive; dry-run by default; passed once at the fixed plan** |
| `kb7-updater-plan.py` | V1.22-only paired-region planner and interruption-model checker | **offline only; no device I/O; not an executor** |
| `kb7-updater-sign.py` | Detached Ed25519 signing, verification, and public-key fingerprinting after complete planner revalidation | **offline authenticity only; never installation authorization** |
| `kb7-updater-executor.py` | Two-read live preflight, durable journal binding and image-derived reconciliation | **read-only CLI; mutation hard-disabled; not an installer** |
| `kb7-updater-scratch-executor.py` | One-operation-per-process replay of the fixed 22-command V1.22 scratch plan, mandatory boundary-9 host termination, and local-only state inspection | **destructive; dry-run by default; current v3 passed once at the fixed plan** |
| `kb7-loader-reentry-campaign.py` | Derive and reverify a fixed proof-Core0 install plus exact-stock restore campaign with a temporary Core1 checksum barrier | **offline only; private artifacts; does not authorize execution** |
| `kb7-loader-reentry-executor.py` | Fixed proof campaign executor with terminal intents, exact full-chip reads, re-entry gate and local inspection | **fixed proof campaign enabled for the exact reviewed campaign (this revision only); general firmware mutation hard-disabled** |
| `../../docs/LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md` | Exact offline safety model, private campaign generation, stop rules and later hardware outline | documentation only |
| `../../docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md` | Exact v3 durable-command-complete/pre-WIP self-termination sequence and stop rules | documentation only |
| `../../docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md` | Observed v3 host-termination, reconciliation, restoration and boot result | documentation only |
| `../../docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md` | Historical exact v2 checkpoint sequence, stop rules and proof boundary | documentation only |
| `../../docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md` | Observed v2 checkpoint, completion evidence and limits | documentation only |
| `WRITE-TEST-PLAN.md` | Exact experimental sequence, remaining failure modes and SPI recovery procedure | documentation only |
| `ERASE-GRANULARITY-TEST-PLAN.md` | Fixed target, exact four-stage sequence, proof limits and SPI recovery procedure | documentation only |
| `F6-ERASE-ENCODING.md` | Calibrated static proof of the erase address units and CDB layouts | documentation only |
| `F6-WRITE-ENCODING.md` | Final program/erase investigation record and safety verdict | documentation only |

`kb7-isp-verify.py` remains useful as a historical diagnostic, but one USB
capture cannot distinguish physical NOR state from a command-read acquisition
failure. Its legacy CLI also exits 0 after region CRC failure and prints an
unsupported diagnosis. Use independent SPI to classify physical flash state.
For USB-path qualification, `kb7-isp-repeat.py` now requires every completed
short read to be byte-exact against the pinned baseline; stable-but-wrong reads
fail. See the
[2026-08-31 incident](../../docs/USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md).

`kb7-isp-write2.py` is deliberately not a general writer. It accepts only the
reviewed marker-program and sector-erase experiment, opens no USB device in its
default dry run, and requires an explicit `--commit` for either destructive
stage. That sequence passed once on the V1.22 development unit at `0x8e000`;
other offsets, lengths, loader revisions, interruption behavior and `F6 19`
remain outside its evidence. Its guards bound host-side mistakes; they cannot
make an incorrect or faulty loader handler safe. For ordinary or production
writes, continue to use the proven external-SPI procedure. This project remains
`flash_approved=false`.

`kb7-isp-erase-granularity.py` is similarly fixed and fail-closed. It uses
sector `0x000c6000`, programs all eight of its 512-byte blocks, and brackets the
sector with adjacent 512-byte guards. The required erased containment envelope
is `[0x000c0000,0x00100000)`, wholly inside the reviewed V1.22 scratch gap; this
bounds plausible 64/128/256-KiB over-erase while making it detectable. Each
stage checks the reviewed 60-KiB preserved-loader flash hash before mutation.
The state-bound fixed plan covers that hash plus every mutation CDB, geometry
and source-file hash, so changing the implementation between stages fails
closed. Each stage opens a fresh USB session without requiring a physical power
cycle, requires an exact full-chip preimage, persists a started state before
mutation, and accepts only its exact full-chip postimage. Read the dedicated
plan before even running its offline dry mode.

The four-stage run has now passed once at this exact target. All target and
guard postimages matched, the complete baseline was restored, and the keyboard
subsequently cold-booted normally. Do not repeat it merely to reconfirm that
same bounded fact.

`kb7-isp-scratch-restart.py` is a separately scoped fixed experiment. It uses
only fixed sectors `0x000c4000..0x000c7fff` inside the same required erased
256-KiB containment envelope. It fully patterns two work sectors and places
non-`0xff` guards immediately outside them. One fixed program and one fixed
erase deliberately stop after WIP clears but before readback. Only a new
process running its read-only `reconcile` stage may classify the result, using
two matching full-chip reads and accepting only the exact intent preimage or
postimage. It never retries automatically. The script is dry-run by default and
has no caller-selected address/CDB/payload/force options. The complete sequence
passed once on the development unit: both no-readback operations reconciled to
exact postimages from two full-chip reads in new processes, cleanup restored
the exact baseline, and normal `5038` operation returned. This validates
command-complete process/libusb-session reconciliation only; it did not
interrupt an operation or remove device power while markers remained. Read the
[dated result](../../docs/USB-ISP-SCRATCH-RESTART-VALIDATION-2026-08-23.md) and
[test plan](SCRATCH-RESTART-TEST-PLAN.md) for the exact proof boundary.

### Fixed scratch-only updater executor harness

`kb7-updater-scratch-executor.py` is a separate control harness for the same
reviewed scratch geometry. It does not consume the paired-firmware bundle and
cannot construct or accept a firmware-region command. Its immutable plan is 18
one-block `F6 06` programs followed by four `F6 15` sector erases, all inside
`[0x000c0000,0x00100000)`. It derives exactly one next operation from a distinct
scratch journal and sends `F6 18` immediately before that operation.

Every committed preflight first publishes `preflight_started` before backend
construction or USB, then obtains two stable exact 32-MiB reads, closes strictly
and publishes boundary 0. Every step similarly publishes raw intent before
backend construction or USB; it normally verifies two exact pre-reads, mutates,
polls WIP, verifies two exact post-reads, closes strictly and publishes the next
boundary. The current v3 plan makes operation index 9 (`program-09` at
`0x000c6000`) a mandatory
exception: after exact CBW/data-OUT and strict program-CSW validation, it marks
the handle abandoned, atomically publishes and reads back
`checkpoint_command_complete`, and self-sends `SIGKILL` before WIP polling,
postread, boundary advance or explicit USB close. Shell status 137 is expected.
The intervening journal `fsync` means this tests durable command completion
followed by host death, not immediate post-CSW death or known WIP activity.

Visible `preflight_started` or raw intent at every operation index is terminal
external SPI. The sole
checkpoint-ready state authorizes one fresh-process, read-only no-recovery
`reconcile`; final `complete` similarly authorizes one finalization pass, while
intermediate verified boundaries are not reconcilable. Ordinary exact postread
is followed by strict USB close and only then boundary publication; a reported
publication error succeeds only when the exact target is visible. Before a
read-only pass opens USB, it atomically consumes its source into
`checkpoint_reconcile_started` or `final_reconcile_started`. A start-publication
error with the exact source retained permits exit 4 and a fresh-process retry
because no USB opened. Once a started state is visible, every backend/open,
transport, verification or close failure is terminal external SPI. A final-
publication error accepts only the exact target; an unclassifiable atomic
result permits local-only inspection, never another USB probe.

Checkpoint reconciliation performs the omitted WIP poll and accepts only the
exact preimage or postimage from two stable reads. Exact postimage advances to
boundary 10 without replay. Exact preimage consumes the attempt, records
`checkpoint_no_effect`, exits 5 and requires external-SPI baseline restoration.
Exact classification and strict USB close precede final publication. A reported
atomic publication error is accepted only if its exact target is visible; a
reported final-clear error is accepted only if the journal is exactly absent.

An atomic publication/readback that cannot be classified in-process reports
`STATE INSPECTION REQUIRED` / exit 4. The only authorized next command is a
fresh local `inspect`; it has no `--commit`, never opens USB, and reports a
permitted dry run or external-SPI action from the exact journal state. It does
not itself authorize USB.

Status 137 is required for experiment-valid continuation. If ready publication
reports an error with exact ready visible, no signal is sent and exit 4 permits
one cleanup reconciliation. If self-`SIGKILL` fails, status 126 is used. Exact
ready permits cleanup in either invalid case, but even an observed boundary 10
must be followed by SPI restoration rather than `program-10`; the journal
cannot encode the shell outcome.

Eligible clean closes check interface-release and kernel-driver-reattach return
codes, never reattach after a failed release, and always perform local handle
close and context exit. Any failure in that sequence is an exit-3 external-SPI
stop.

Preflight and reconciliation instantiate the verifier-only transport, whose
whitelist cannot issue `F6 06`, `F6 15`, `F6 18` or a data-OUT program phase.
V3 additionally disables endpoint-recovery traffic in that transport. The
checkpoint-ready state binds a process-instance nonce; the process that wrote
it cannot reconcile it. This is abrupt userspace termination after a validated
BOT command and durable journal publication, not a physical cable disconnect,
device-power cut or proven NOR-pulse interruption.
Committed commands also hold one persistent, private per-journal lock from the
authoritative state read through USB close and publication; a concurrent
invocation refuses before opening USB.

The current v3 harness and its fake-transport/journal tests pass offline, and
its plan SHA-256
`c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653`
has completed once on the development unit. The checkpoint process ended with
the planned status 137; an accidental duplicate `step` was rejected before USB;
fresh-process reconciliation completed the omitted WIP poll and classified two
reads as the exact boundary-10 postimage without replay; cleanup restored the
exact baseline; and normal `5038` keyboard operation returned. See the
[v3 validation record](../../docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md).
Its historical v2 mandatory-checkpoint plan also completed once:
the fixed command and WIP poll completed without postread, a fresh process using
the verifier-only backend classified two reads as the exact boundary-10
postimage without retry, and the remaining plan restored the exact baseline.
Final reconciliation cleared state and a separate verifier reproduced the same
32-MiB hash with all three region CRCs valid. The owner also confirmed normal
operation. The preceding v1 22-operation plan passed once through the
earlier orchestration path: every ordinary exact boundary was accepted, final
new-process
reconciliation cleared the journal at SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`,
and the separate read-only verifier entry point reproduced the same 32-MiB
image before the owner reported normal keyboard operation. Both live readers use
the same loader and SoC `F6 05` flash-controller path. Neither run physically
interrupted a command, tested power loss or touched firmware regions. Read the
[fixed scratch executor status and test plan](../../docs/USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md)
for its exact sequence and stop rules, the
[v3 host-termination test plan](../../docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md),
[v3 validation record](../../docs/USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md),
historical [mandatory active-intent test plan](../../docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
and [v2 validation record](../../docs/USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md)
for the completed historical v2 campaign, and the
[completed validation record](../../docs/USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md)
for the historical v1 evidence and proof boundary.

### Fixed loader-reentry proof campaign

`kb7-loader-reentry-campaign.py` is narrower than the paired updater planner.
It accepts only the pinned V1.22 baseline and exact 1,228-byte
`recovery-proof` Core-0 raw identity. The stable proof image keeps stock Core 1
byte-exact. During install and restore it temporarily poisons one bit in one
fixed Core-1 sector so every dense Core-0 prefix retains an independently
invalid opposite-core checksum; that sector is rebuilt to exact stock before a
rank-32 Core-0 checksum gate is committed last. The reverse half converges to
the exact complete baseline. Header, loader, manifest and every byte after the
Core-1 envelope have zero operations.

The builder imports no USB library and its descriptor explicitly does not
self-authorize execution. `campaign.json`, the proof sector image, simulation
and all journals are owner-local artifacts excluded from the public tree.

`kb7-loader-reentry-executor.py` is a separate fixed-domain implementation. It
has only `preflight`, `step`, `validate-reentry`, `finalize` and local-only
`inspect`; there is no raw flash authority. A committed step would publish a
terminal exact intent before backend construction, take two exact full-chip
pre-reads, issue exactly one internally derived command, take two exact
post-reads and strictly close before publishing the next boundary. No ordinary
intent is USB-reconcilable. Re-entry validation consumes its state before USB
and requires the same topology, a new USB address and two exact proof-image
reads before restore is authorized.

The supporting sources, policy, normalized executor source and exact owner
campaign ID are pinned. The two private baselines independently reproduce 168
operations, proof full-image SHA-256
`58780441a9a5d6208aa2056c778e73b480e837d8b9f61c6b0be5629079307da9`,
one barrier sector at `0x00022000`, and exact stock restoration. On this
mutation-enabled branch both gates are true for the exact reviewed campaign
only; the hardware-validation branch keeps both false and the preflight-only
branch enables only the read-only preflight. A
2026-08-31 preflight exposed independently SPI-confirmed two-byte physical
corruption; after exact SPI restoration, a separate full USB capture exposed
widespread command-aligned acquisition corruption, traced on 2026-09-02 to the
NOR lead stubs and cleared by the fixed short-chunk sweep (400/400). Live reads
are compared exactly below the post-image live region; the stock settings
storage above it is recorded and stability-checked, never baseline-exact. Raw
authority and the general paired-firmware mutation path remain unavailable. See the
[read-reliability incident](../../docs/USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md).
Passing the sweep would permit review of a read-only full preflight revision,
not mutation; mutation needs a later exact full-preflight result and separate
pin review.
Read the historical
[fixed campaign runbook](../../docs/LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md)
for the model and stop rules before any later bounded hardware test. This
does not change the general paired-firmware executor's read-only lock.

### Offline paired updater planner

`kb7-updater-plan.py` is the first software-only step toward a constrained USB
updater. It requires two distinct matching 32-MiB V1.22 captures and the two
locally built replacement ELFs. It preserves the header, loader and manifest
byte-for-byte, emits only the two clean replacement sector envelopes, balances
their final checksums to the unchanged manifest values, and checks the
normative poison/stage/Core1-gate/Core0-gate transaction.

The firmware images contain matching build-pair markers and ABI v2 checks so a
stock/custom or independently built pair parks before application hardware.
The final commit gates differ from their staged images by exactly 32 requested
`1 -> 0` transitions, and their CRC transforms are independently required to
have rank 32. The saved plan and report are content-hashed and independently
recomputed by the `simulate` command.

This remains an unsigned, full-image-bound planning artifact. It does not know
a unique physical-device identity. The separate read-only paired-firmware
executor scaffold adds live loader, USB topology and session binding, but
byte-identical units at the same topology are still indistinguishable. The
planner imports no
USB library and exposes no execute, commit, force, arbitrary-offset or raw-CDB
option. It does not prove physical torn-erase behavior, custom-firmware recovery
or board correctness. See the
[offline updater design](../../docs/USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md)
for the exact state machine and evidence boundary.

### Detached offline authentication

`kb7-updater-sign.py` adds optional detached Ed25519 authentication without
changing the bundle or enabling execution. Both `sign` and `verify` first run
the planner's complete bundle verification against two matching owner-local
32-MiB baselines. The signed statement binds every bundle file, the bundle ID,
baseline, exact target, pair ID, signing-key SPKI fingerprint, and false
authorization flags.

Verification requires `--trusted-key-sha256`; the public key alone is not a
trust root. The project has not provisioned a release key or independently
distributed fingerprint yet, so this is a tested mechanism rather than a
signed project release. Generated envelopes and all keys stay outside the
bundle and public tree. See the
[authentication design](../../docs/OFFLINE-UPDATER-AUTHENTICATION-2026-08-23.md).

### Read-only updater executor scaffold

`kb7-updater-executor.py` reloads and independently verifies the complete
owner-local plan before opening USB. `preflight` requires two identical 32-MiB
live reads that exactly equal the planned V1.22 baseline, then binds a durable
journal to the live loader, topology, flash anchors, bundle and tool-source
hashes. `reconcile` again requires two identical full reads and classifies only
exact modeled boundaries or a transition confined to the journal's active
operation unit. It never treats the journal as flash-state authority and never
authorizes an automatic retry.

The internal one-operation state engine is fault-injected with fake transports
at intent, mode, transport, polling, readback and journal boundaries. The public
CLI offers only `preflight` and `reconcile`; the live mutation adapter is
hard-disabled. This is diagnostic/restart architecture, not a firmware flasher.
See the
[executor scaffold record](../../docs/USB-UPDATER-EXECUTOR-SCAFFOLD-2026-08-23.md).

The live read-only executor path has now also been exercised on the development
unit in two separate processes: preflight and reconcile both classified the
same exact stock 32-MiB image at boundary 0 while mutation remained disabled.
That is a diagnostic/reopen result, not evidence for firmware-region writes.

---

## SN_FWIN region map (V1.22)

| Region | Store offset | Length | Load VMA | CRC |
|---|---|---|---|---|
| header | `0x0` | `0x1000` | — | none |
| loader | `0x1000` | `0xf000` | `0x0` | none |
| manifest | `0x10000` | `0x1000` | — | — |
| 0 (core0) | `0x11000` | `0xf35c` | `0x00000000` | `0xc3f43a6f` |
| 1 (core1) | `0x21000` | `0x6b168` | `0x10000000` | `0xc8ed2815` |
| 2 (assets) | `0x100000` | `0x146af8c` | `0x60100000` | `0xaa83e9a3` |

Region CRC = `sum(zlib.crc32(chunk)) mod 2**32` over `0x10000`-byte chunks.
**The loader validates every region CRC at boot** and falls back to ISP mode on
any failure — verified empirically: 52 corrupted bytes in region 2 (asset pixel
data, functionally cosmetic) were enough to stop the keyboard booting.

Free space: `0x8c168`–`0x100000` (~464 KiB, all `0xFF`). The post-image tail is
**not** free — user settings, keymaps and RGB profiles live at `0x1a00000` and
are rewritten during normal operation.
