# KB7 USB-ISP erase-footprint test plan

Status: **completed successfully once on one owner-controlled KB7 on
2026-08-23**. The exact evidence is recorded in
[`../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md`](../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md).

`kb7-isp-erase-granularity.py` is a fixed, destructive laboratory experiment,
not a firmware updater. Its purpose is to answer the one question left open by
the successful `0x0008e000` marker cycle: does the V1.22 loader's normal-NOR
`F6 15` command have an observable erase footprint of exactly one 4-KiB sector?

The script is dry-run by default. It has no caller-selectable address, payload,
length, erase type or raw-CDB option. A committed run still requires the proven
external-SPI recovery path and can require a full-chip restore.

## Fixed geometry and why it was chosen

The experiment accepts only the reviewed V1.22 manifest geometry, the reviewed
preserved-loader bytes and a complete 32-MiB owner baseline. It requires the
flash window `[0x00001000,0x00010000)` (the complete 60-KiB preserved loader)
to have SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`.
This pins the code implementing the tested commands, rather than relying only
on its USB identify and descriptor replies. The manifest-derived erased scratch
gap is `[0x0008d000,0x00100000)`. Within it, the script fixes these locations:

| Role | Flash range |
|---|---|
| Required erased containment envelope | `[0x000c0000,0x00100000)` |
| Lower guard sector | `[0x000c5000,0x000c6000)` |
| Lower programmed guard block | `[0x000c5e00,0x000c6000)` |
| Populated target sector | `[0x000c6000,0x000c7000)` |
| Upper guard sector | `[0x000c7000,0x000c8000)` |
| Upper programmed guard block | `[0x000c7000,0x000c7200)` |

The entire 256-KiB envelope from `0x000c0000` through `0x000fffff` must be
`0xff` in the baseline. The target `0x000c6000` was chosen because the 64-KiB,
128-KiB and 256-KiB erase-aligned ranges containing it all begin at
`0x000c0000` and remain inside that erased envelope. Thus those plausible
larger erase mistakes do not reach a declared firmware region, while the
immediately adjacent non-`0xff` guards make such an over-erase observable.

Every byte of the target sector is programmed with a deterministic non-`0xff`
pattern, split into eight distinct 512-byte blocks. Therefore an under-erase
leaves an observable target byte. Every byte of both 512-byte guard blocks is
also non-`0xff`; an erase extending even one byte below or above the target
damages a guard. Every verification compares the complete 32-MiB image, so a
change anywhere else is also fatal.

## Preconditions

Do not run any committed stage unless all of these remain true:

- two independently acquired full-chip backups from this keyboard are retained
  separately and compare byte-for-byte equal;
- the same 3.3-V external-SPI setup has already completed a full-chip restore,
  flashrom verification and independent readback comparison;
- the keyboard is in `10f5:5037` ISP mode and the external programmer's SPI
  wires are physically disconnected;
- the baseline is a fresh, exact 32-MiB USB-ISP read of this device, and its
  pathname and the state-file pathname are absolute, distinct and outside the
  repository;
- bytes `[0x00001000,0x00010000)` in that baseline have SHA-256
  `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
- the state-file path does not already exist and is not a symlink before
  `prepare`; and
- the operator accepts that any anomalous committed result ends the USB test
  and may require a full-chip external-SPI restore.

The tool independently refuses a short or invalid baseline, an unexpected
header, boot configuration, preserved-loader window hash, USB loader identity,
manifest, region geometry, scratch gap, programmed byte anywhere in the
containment envelope, stale state, different USB topology, different loader
fingerprint, different baseline or any unexpected complete preimage. Every
committed stage checks that same preserved-loader hash again in its fresh
full-chip live preflight. The fixed expected hash is also bound into the saved
stage state.

Do **not** physically power-cycle or reset the keyboard while any experiment
marker remains. Each successful invocation below exits and closes its USB handle;
the next invocation opens a fresh USB session while the device stays powered in
ISP mode. Do not skip, reorder or combine stages.

## Operator sequence

Use the same baseline and state paths for every invocation. First run each
stage without `--commit`; a dry run performs only offline baseline, plan and
state checks and does not open the USB device. Run its committed form only when
the dry-run plan is exactly the one documented here. The fixed plan SHA-256
must be
`a68642a348b18ee27a2f1cfdb6c8137aeff43c0ce14487f9c765c4c76e9be783`;
the baseline and expected-image hashes are necessarily device-baseline-specific.

### What the fixed plan hash binds

The plan hash is computed from a canonical description and saved in every
stage state. It binds all of the following, not merely the target offset:

- flash size `0x02000000` (33,554,432 bytes), transfer block size `0x0200`
  (512 bytes), and erase-sector size `0x1000` (4,096 bytes);
- the preserved-loader hash, containment envelope, guard/target sector offsets,
  ten program offsets and all ten deterministic payload hashes;
- the literal 16-byte CDB for each of the ten `F6 06` operations and each of the
  three `F6 15` operations shown below;
- sub-16-MiB address-mode subcode `0x18`, whose complete no-operand CDB is
  `f6 18 00 00 00 00 00 00 00 00 00 00 00 00 00 00`; and
- the exact source bytes used for command construction, transport and
  verification:

| Bound source | SHA-256 |
|---|---|
| `kb7-isp-erase-granularity.py` | `bb08fba40aefad72f32969d266f06509bbd38c352c44edec5853accd7c6d2ebb` |
| `kb7-isp-write2.py` | `f706cb355297e4b010fd49f10a1c0e68834d73e99a33005780046ced4e1dc6e5` |
| `kb7-isp-verify.py` | `9b19d393cf64c66168e08de2f3d4fe352a85a2fd69545e374dee0fa015dea338` |

Changing any bound command, constant, payload or source file changes the plan
hash; a state created by the reviewed files then cannot authorize a later stage
under different files. This is a consistency and stale-state guard, not a
signed-software or hostile-host security boundary.

```sh
# Stage 1: offline plan, then prepare both guards and all eight target blocks.
sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage prepare \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json

sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage prepare \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json --commit

# Stage 2: offline plan, then test the target sector's erase footprint.
sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage erase-target \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json

sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage erase-target \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json --commit

# Stage 3: offline plan, then remove only the lower guard.
sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage cleanup-lower \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json

sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage cleanup-lower \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json --commit

# Stage 4: offline plan, then remove the upper guard and restore the baseline.
sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage cleanup-upper \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json

sudo python3 tools/flash-access/kb7-isp-erase-granularity.py \
  --stage cleanup-upper \
  --baseline /absolute/path/kb7-usb-baseline.bin \
  --state-file /absolute/path/kb7-erase-granularity-state.json --commit
```

Stop on any refusal, `UNKNOWN RESULT`, USB anomaly, timeout, mismatch, signal or
nonzero exit status from a committed invocation. Do not retry that mutation and
do not run the next stage. Preserve the output and state file for diagnosis and
switch to external-SPI inspection/recovery.

## Exact device-command plan

Every full-chip preflight or postflight selects `F6 17` and reads exactly
32 MiB with strict `F6 05` Bulk-Only Transport checks. Every mutation is below
16 MiB and is preceded by `F6 18`, matching the vendor sub-16-MiB sequence.
Every program and erase is followed by `F6 01` ready polling. The state file is
persisted with a `*_started` status before each mutating command. Before any
mutation, the stage checks both the exact expected 32-MiB preimage and the
preserved-loader window hash above. State binds that loader-window hash in
addition to the USB replies, stable descriptor fingerprint, manifest, baseline,
fixed plan and expected stage images.

### Stage 1 — `prepare`

After an exact baseline preflight, the script issues ten separate one-block
program operations in this fixed order. Each CDB transfers exactly 512 payload
bytes. After every individual block, it rereads and exactly compares all
32 MiB before authorizing the next block.

```text
F6 18; F6 06 00 60 0c 5e 00 00 01 00 00 00 00 00 00 00  # lower guard
F6 18; F6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00  # target block 0
F6 18; F6 06 00 60 0c 62 00 00 01 00 00 00 00 00 00 00  # target block 1
F6 18; F6 06 00 60 0c 64 00 00 01 00 00 00 00 00 00 00  # target block 2
F6 18; F6 06 00 60 0c 66 00 00 01 00 00 00 00 00 00 00  # target block 3
F6 18; F6 06 00 60 0c 68 00 00 01 00 00 00 00 00 00 00  # target block 4
F6 18; F6 06 00 60 0c 6a 00 00 01 00 00 00 00 00 00 00  # target block 5
F6 18; F6 06 00 60 0c 6c 00 00 01 00 00 00 00 00 00 00  # target block 6
F6 18; F6 06 00 60 0c 6e 00 00 01 00 00 00 00 00 00 00  # target block 7
F6 18; F6 06 00 60 0c 70 00 00 01 00 00 00 00 00 00 00  # upper guard
```

Success requires the exact expected full-chip prepared image and saves state as
`prepared_verified`.

### Stage 2 — `erase-target`

This stage requires the exact prepared image and its identity-bound state, then
sends:

```text
F6 18
F6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00
```

`0x0630` is the big-endian 16-bit 512-byte-block index
`0x000c6000 >> 9`. Success requires all 4,096 target bytes to be `0xff`, both
boundary guard blocks to survive byte-for-byte, and every other flash byte to
equal the expected image. It saves `target_erased_verified`.

This is the experiment's proof point. Complete stages 3 and 4 immediately to
remove the guards; do not power-cycle first.

### Stage 3 — `cleanup-lower`

This stage requires the exact target-erased image and sends:

```text
F6 18
F6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00
```

`0x0628` is `0x000c5000 >> 9`. Success requires only the upper guard to remain
and saves `lower_cleaned_verified`.

### Stage 4 — `cleanup-upper`

This stage requires the exact lower-cleaned image and sends:

```text
F6 18
F6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00
```

`0x0638` is `0x000c7000 >> 9`. Success requires the final complete 32-MiB image
to match the original baseline byte-for-byte. Only then does the script remove
the state file and report completion.

## What the completed pass proves

For this one device, preserved V1.22 loader, normal-NOR selection, flash state
and target, the completed pass establishes that the **observable** effect of
the tested `F6 15` command was exactly `[0x000c6000,0x000c7000)`:

- every initially programmed byte inside that 4-KiB sector reads back erased;
- programmed bytes immediately below and above it survive exactly; and
- the rest of the 32-MiB image has no observable difference.

The prepared image, target-erased image, both cleanup images and final baseline
all matched their exact full-chip predictions. A separately invoked final USB
capture also matched the baseline, the state was cleared, and the owner later
confirmed normal operation after a cold boot.

That is sufficient evidence for the erase footprint needed by the next updater
design step. It does not prove undocumented internal behavior, atomicity,
power-loss recovery, endurance, every offset, an above-16-MiB mutation, another
loader revision or another device. It does not validate `F6 19`; that alternate
flash-type path remains untested. It does not by itself validate arbitrary
image planning or make a general USB updater safe or complete.

The result is deliberately scoped to an observable exact 4-KiB programmed-data
footprint at this tested target. External SPI remains the recovery path and
ordinary write method. Repeating this destructive run merely to reconfirm the
same target is unnecessary.

## Recovery procedure

If any committed stage fails or becomes ambiguous, do not retry over USB. Keep
the state and transcript, power the keyboard down, connect the proven 3.3-V SPI
programmer, hold `MCU_RST` low, and then power the programmer/board in the same
sequence used for the successful recovery rehearsal. Never leave an unpowered
programmer attached to the SPI signals.

Restore and independently reread the exact baseline that matched the stage-1
preflight:

```sh
flashrom -p 'serprog:dev=/dev/ttyACM0:921600,spispeed=1M' \
  -c 'MX25L25635F/MX25L25645G' \
  -w /absolute/path/kb7-usb-baseline.bin --progress

tools/flash-access/kb7-read-1m.sh \
  /absolute/path/kb7-post-restore.bin

sha256sum /absolute/path/kb7-usb-baseline.bin \
  /absolute/path/kb7-post-restore.bin
cmp /absolute/path/kb7-usb-baseline.bin \
  /absolute/path/kb7-post-restore.bin
```

Require flashrom verification plus the independent hash and `cmp` to pass.
Then power down, physically disconnect the programmer's SPI wires, release
reset, cold-boot and confirm normal `10f5:5038` enumeration and keyboard
operation.
