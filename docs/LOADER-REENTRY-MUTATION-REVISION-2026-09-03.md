# Loader-reentry mutation-enabled revision and hardware runbook

Branch `loader-reentry-mutation-enabled`, built 2026-09-03 on top of the
preflight-only branch after the read-only preflight passed under the
post-image live-region policy (journal `boundary_verified` 0, live region
`04b21e7889e26171b3d2b338554672faa3f86a40e550d566a89f2eafa67d70b4`).

## What this revision enables

`LIVE_PROOF_CAMPAIGN_ENABLED = True` in addition to the read-only preflight,
for the exact reviewed campaign
`1ce62e95ee2c6c84b5abb8996f7964bacae661869152ead20f5c7138b2b0b508`
(proof image `b0b3b75ab06bd00b152f86446de623b9029ff3ab9d164f6f4387243d2556b272`,
1260 bytes; proof full image
`58780441a9a5d6208aa2056c778e73b480e837d8b9f61c6b0be5629079307da9`).
Every other campaign identity, any pin drift and the general paired-firmware
executor stay refused in the CLI, every live entry point and both USB backends.
Pins: policy `c336f62c097234aff074bb8da2dcc25fdf6604413df977511f63bb52e0388bde`, executor descriptor `7247661fa9f3aeddac2a6c99320cde95411c176733f6513d017ec37b4dc625a0`, executor source `64af8a974519af13044a28e61902c59f6cad03173208f3d01babad4b505055f1`.

The 168 operations are the campaign's: 32 install (Core-0 envelope
`[0x00011000,0x00021000)` plus the temporary Core-1 barrier sector
`0x00022000`) and 136 restore back to the exact stock baseline. Header, loader,
manifest and everything after the Core-1 envelope have zero operations. Each
committed `step` publishes a terminal intent, takes two exact full-chip reads,
executes exactly one operation, takes two exact reads, closes strictly and only
then publishes the next boundary. Every read is byte-exact against the modelled
boundary image below `0x0156b000`; the live region above it must equal the
value recorded at the previous boundary.

## Prerequisites

- External programmer physically detached; NOR lead stubs at ~20 mm; the
  short SPI extension leads and the programmer ready on the bench but not
  attached (recovery means soldering to a pigtail first).
- Bare motherboard, exactly one `10f5:503d` hub and one keyboard on the bus,
  no mass-storage mount, KDE automount off.
- `make -C replacement_fw recovery-proof` in this checkout; the campaign
  builder `verify` against the two owner baselines and the private campaign
  directory; the executor dry run for `preflight`.
- Temporary sudo for the executor's libusb access; revoke it afterwards.
- A fresh journal path for this revision: journals from earlier revisions are
  refused because they bind a different executor source hash.

## Operator notes from the final review

- Expect an exit 3 as a plausible outcome, not a surprise. The campaign reads
  the whole chip four times per operation, roughly 5.5 million `F6 05`
  commands in all, and the read path's residual fault rate is only bounded
  near one in ten thousand. Any single wrong read after an intent is terminal
  and means the SPI restore below, then a restart from step 0 with a new
  journal. Have the extension leads cut and the programmer on the bench before
  starting.
- Run every `--commit` detached from the terminal session (`setsid nohup …`),
  never in a tool or shell that can be interrupted; a hang-up or Ctrl-C after
  an intent is also an exit 3.
- Before `validate-reentry`, check passively that the loader came up at a new
  USB address: read `/sys/bus/usb/devices/3-2.2/idProduct` (`5037`) and
  `/sys/bus/usb/devices/3-2.2/devnum`, and compare the latter with the
  journal's `current_usb_address`. If they are equal, power-cycle again before
  running the command; the executor treats an unchanged address as a stop and
  consumes the journal.
- usb-storage probes the loader between every step. Make automounting provably
  off for the session, for example `systemctl mask --runtime udisks2` and an
  empty `lsblk` mount column, not only a desktop setting.
- The executor runs under sudo, so its journal is root-owned; run `inspect`
  under sudo as well, or `chown` the journal after each session.
- An exit 3 from `validate-reentry` or `finalize` comes from a read-only
  phase: no write was possible, but the rule is the same because the campaign
  state is terminal. A finalize mismatch confined to the live region after an
  accidental stock boot is settings drift, not corruption; it still needs the
  SPI path to re-establish a clean state for the campaign.

## Sequence

1. Enter `10f5:5037` with the vendor HID mode-switch.
2. `preflight --commit`: expect exit 0, `boundary_verified` 0, live region
   recorded.
3. Install: run `step --commit` once per operation while `inspect` reports
   `step_dry_run`, in the same powered session, checking that each returned
   `boundary_index` increases by one and that every exit is 0. The 32nd step
   returns `proof_installed`; `inspect` then reports
   `cold_boot_then_validate_reentry_dry_run`.
4. Power the keyboard off and on. The proof Core 0 boots, masks interrupts,
   copies the preserved loader to PRAM and resets into it; the loader should
   enumerate as `10f5:5037` by itself, at a new USB address, without the HID
   mode-switch. If it does not enumerate within a minute, stop: do not send
   the mode-switch, do not open USB; the unit needs the SPI restore.
5. `validate-reentry --commit`: expects the same topology path, a new USB
   address, two exact reads of the proof full image below the live region and
   the live region unchanged since `proof_installed`. Returns `restore_ready`.
6. Restore: `step --commit` per operation while `inspect` reports
   `step_dry_run`, 136 times, in that same powered session. The last returns
   `complete`.
7. `finalize --commit`: two exact reads of the stock baseline below the live
   region, live region unchanged since `complete`, strict close, journal
   cleared.
8. Separate verifier capture (`kb7-isp-verify.py --full-chip -o`), require
   all three region CRCs and byte equality with the baseline below the live
   region.
9. Power-cycle: require `10f5:5038` and normal keyboard operation.

## Stop rules

- Exit 2: locked or invalid invocation before USB; nothing happened.
- Exit 5 (preflight transport or close stop): no write occurred; issue no more
  USB commands in that powered session; power-cycle; move the journal aside;
  new journal.
- Exit 6 (preflight image differs below the live region): no write occurred;
  verify independently over SPI; write only if the SPI read itself differs
  from the baseline.
- Exit 4: state inspection required; run `inspect` locally; no USB.
- Exit 3 after an intent (`intent`, `reentry_started` or `finalize_started`
  visible): the executor sends no further USB command and neither may the
  operator. Restore the exact baseline over external SPI, verify by an
  independent SPI read, cold boot, require `10f5:5038`.
- A step that reports the live region changed between sessions or during an
  operation is an exit 3 with the same rule.
- Never attach an unpowered programmer; never leave long leads on the bus.
- The full-chip SPI restore that every exit 3 depends on is written out in
  `tools/flash-access/README.md` under "Full-chip SPI restore".

## Proof boundary

A complete run shows, on this V1.22 unit, that one checksum-valid custom
Core 0 executes the interrupt-masked SRAM relocation path and returns to the
untouched stock USB loader, and that the fixed campaign restores the exact
stock image below the live region. It does not authorize general firmware
installation, prove arbitrary application recovery, validate a power-cut or
torn-NOR path, or make the stock loader physically immutable. The general
paired-firmware executor remains mutation-locked and external SPI remains the
final recovery mechanism.
