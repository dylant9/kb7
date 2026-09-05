# Region-1 proof campaign runbook

Written: 2026-09-05, after the independent review of the offline revision
(CLEAN WITH NON-BLOCKING NOTES, notes closed in the following commit).
Status: the preflight-only revision on branch
`region1-reentry-preflight-only`
([record](REGION1-REENTRY-PREFLIGHT-ONLY-REVISION-2026-09-05.md)) passed
its read-only preflight on 2026-09-05
([result](REGION1-REENTRY-PREFLIGHT-2026-09-05.md)); the mutation-enabled
revision is branch `region1-reentry-mutation-enabled`
([record](REGION1-REENTRY-MUTATION-REVISION-2026-09-05.md)), pending its
own independent review. This runbook describes the two gated
revisions, in order, and the hardware sequence each runs. Nothing here
authorizes execution; the gates do.

## Revisions

1. **Preflight-only revision.** A separate branch that flips only
   `LIVE_READ_ONLY_PREFLIGHT_ENABLED` to `True`, re-pins the policy and
   descriptor hashes, and mirrors the gate in the audit's expected-gate
   table. It permits exactly one read-only command, `preflight --commit`,
   which opens the loader, takes two full-chip reads, compares them with
   the exact baseline below the live region, records the live region, and
   writes journal boundary 0. It can neither program nor erase.
2. **Mutation-enabled revision.** A second branch on top of the first that
   flips `LIVE_PROOF_CAMPAIGN_ENABLED` to `True` for campaign `9a582f1c…`
   only, after its own independent review. Only then do `step`,
   `validate-reentry` and `finalize` accept `--commit`.

Journals bind the executor source hash, so each revision runs its own
preflight; a journal from one revision is refused by the next.

## Before the session

- Board bare, USB only, the ~20 mm SPI pigtails insulated and nothing
  attached to them. Long stubs on the bus corrupt reads
  (`USB-ISP-READ-RELIABILITY-VALIDATION-2026-09-02.md`), and a read fault
  during stock region 0's region-1 copy also trips its first-word check and
  parks the unit in the stock failure path.
- The programmer, short extension leads and the exact baseline on the
  bench, ready for the full-chip SPI restore in
  `tools/flash-access/README.md`. Expect exit 3 as a plausible outcome; the
  campaign issues about 160 full-chip reads, and any single wrong read after
  an intent ends it.
- Automount provably off for the session: `systemctl mask --runtime --now
  udisks2`, then require `systemctl is-active udisks2` to print `inactive`
  and `lsblk`/`mount` to show no `10f5` device before the first `--commit`.
  A mask alone does not stop a running instance. usb-storage still probes
  the loader between steps; after entering the loader read
  `/sys/bus/usb/devices/3-2.2/power/control` and set it to `on` if it reads
  `auto`, since the loader is a new device and gets the default policy.
- Temporary sudo drop-in for the session, removed afterwards. The
  executor's journal is root-owned; run `inspect` under sudo too.
- Every `--commit` run as a transient root service (`sudo systemd-run
  --unit … --collect --property=WorkingDirectory=… --setenv=PYTHONDONTWRITEBYTECODE=1
  /bin/sh -c '/usr/bin/python3 … > log 2>&1; echo exit=$? >> log'`) and its
  log polled; background shells were killed mid-run in earlier sessions,
  and a hang-up after an intent is an exit 3. Name the interpreter by
  absolute path: the service resolves `/usr/bin/python3` (3.14 on this
  host) while the offline checks ran under 3.13; every pin and the campaign
  identity recompute identically under both, and the first journal of the
  session must show `executor_source_sha256` equal to this revision's
  executor source and `implementation_sha256` `bbb87032…`. `systemctl stop`
  or a collected failure SIGTERMs the whole unit, so the `exit=` line is
  never written and the journal stays at its last published state, which
  after an intent is `intent` (`inspect` reports `external_spi_only`); the
  redirected log file is the only record because `--collect` discards the
  unit's journal entry.

## Sequence

All commands take `--baseline-a`, `--baseline-b` (the two exact captures),
`--proof-core1-elf` (the reviewed `region1-reentry-proof.elf`, raw
`e753380b…`), `--campaign` (the private campaign directory, ID
`9a582f1c…`) and `--journal` (a new path outside the checkout).

1. Enter the loader with the vendor mode-switch script; require
   `10f5:5037`.
2. `preflight --commit` (preflight-only revision or later): exit 0 with
   journal boundary 0 and the recorded live-region hash. Exit 5 or 6 means
   stop, power-cycle, new journal; 6 means verify independently by SPI
   first.
3. `step --commit`, one process per operation, twenty times. The driver
   loop must run `inspect` between steps and stop on anything but
   `boundary_verified`. Operation indices are 0-based, as in the campaign
   descriptor: operation 0 is the poison program; 1 erases the patch sector
   and 2 to 9 program it under the poison and the erased gate; 10 erases
   the poison sector and 11 to 18 program it back to stock; 19 programs the
   gate. After the twentieth step the journal reads `proof_installed`.

   Operations 0 and 19 (and 20 and 39 in the restore direction) are the
   first `F6 06` programs this unit has ever received onto a 512-byte block
   that already holds data: the payload equals the block's current bytes
   with a few bits cleared, and the model treats the program as a bitwise
   AND. Every validated program so far targeted erased bytes. The campaign
   is ordered so that this assumption is tested at the cheapest point:
   operation 0 touches only the poison sector `0x22000`. If the loader's
   program path does anything other than a plain page program, the post-read
   fails or the command errors, and the campaign ends with exit 3 before the
   patch sector has been touched, with the loader, header, manifest and
   region 0 untouched. An exit 3 at step 0 whose mismatch is confined to
   sector `0x22000` is therefore this cause, not a read fault. Record the
   observed behaviour of the first programmed-block program as a result of
   the run either way.
4. Power-cycle. Stock region 0 boots, copies the patched region 1 into
   DRAM, calls the proof at `0x1004a525`; the proof masks interrupts,
   takes VTOR, writes the loader marker and relocates the preserved loader
   into PRAM. The loader consumes the marker and enumerates `10f5:5037`.
   Read `/sys/bus/usb/devices/<port>/idProduct` and `devnum` passively.
   If `devnum` equals the journal's `current_usb_address`, power-cycle
   again before continuing; an unchanged address is a stop.
5. `validate-reentry --commit`: two full-chip reads must equal the exact
   proof image below the live region, with the live region as recorded.
   Journal `restore_ready`.
6. `step --commit` twenty more times (operations 20 to 39): poison,
   rebuild the patch sector to stock with the restore gate erased, restore
   the poison sector, program the restore gate. Journal `complete`.
7. `finalize --commit`: two reads equal the exact baseline below the live
   region; the journal is cleared.
8. Verifier capture with `kb7-isp-verify.py`; then cold boot and require
   `10f5:5038` and normal keyboard operation.

## Stop rules

| Exit | Meaning | Action |
|---|---|---|
| 2 | locked, argument or state error before any USB command | fix and retry; nothing changed |
| 4 | state inspection required | run `inspect` locally; no USB action |
| 5 | read-only preflight stopped on transport | no mutation happened; power-cycle before a new journal |
| 6 | read-only preflight readback did not establish the baseline | verify by external SPI; write only if the independent read differs |
| 6 from `step` | a leftover `preflight_started` journal | not an SPI case: follow the original preflight output, move the journal aside, start a new preflight |
| 3 | external SPI recovery required | no further USB command in this powered session; full-chip SPI restore, then restart from step 0 with a new journal |

An exit 3 from `validate-reentry` or `finalize` comes from a read-only
phase: no write was possible, but the campaign state is terminal all the
same. A finalize mismatch confined to the live region after an accidental
stock boot is settings drift, not corruption; it still needs the SPI path
to re-establish a clean campaign state.

## What a pass proves and does not prove

A pass proves that one checksum-valid custom region 1, running under the
untouched stock region 0 from the DRAM-backed aperture, can deliberately
return to the untouched stock USB loader, and that the fixed campaign can
install and remove it through the loader alone. It does not prove recovery
from a region 1 whose entry never reaches the takeover, from code that
damages clocks or peripherals before it, or from a physically damaged
flash. External SPI remains the final recovery route for those.
