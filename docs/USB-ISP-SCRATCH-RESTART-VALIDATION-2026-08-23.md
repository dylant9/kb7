# USB-ISP multi-sector/restart validation

Date: 2026-08-23

## Outcome

The fixed experiment in
[`kb7-isp-scratch-restart.py`](../tools/flash-access/kb7-isp-scratch-restart.py)
completed successfully on one owner-controlled KB7 using the preserved V1.22
loader and the normal-NOR sub-16-MiB path.

The experiment programmed two complete adjacent work sectors, placed a
non-`0xff` guard immediately outside each one, erased all four involved sectors,
and restored the complete 32-MiB baseline. Two operations deliberately ended
after the loader reported ready but before any post-readback. In each case, a
new Python process and libusb/BOT session read the entire flash twice,
classified the exact postimage, and advanced the durable state without
automatically replaying the command.

After cleanup, a separately invoked final USB capture was byte-identical to the
baseline and all three declared manifest-region checksums passed. The state
file was cleared. The owner then power-cycled the keyboard and reported normal
`10f5:5038` enumeration and a working KB7.

This is a successful **command-complete process/session restart** result. It is
not a physical mid-command disconnect or power-loss result, and it does not
authorize firmware-region execution.

## Bound identity and baseline

The run was bound to:

- one development unit;
- fixed plan SHA-256
  `d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b`;
- preserved loader `[0x1000,0x10000)` SHA-256
  `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
- two distinct, byte-identical 33,554,432-byte owner captures; and
- baseline SHA-256
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.

The reviewed V1.22 manifest geometry was required. The entire aligned
containment envelope `[0x000c0000,0x00100000)` was `0xff` before mutation.
External SPI recovery had already been rehearsed and remained available, with
the programmer physically disconnected during USB operation.

## Fixed layout and preparation

The tool exposed no caller-selectable address, payload, CDB, force, or skip
option. Its fixed layout was:

| Purpose | Range |
|---|---:|
| Lower guard block | `[0x000c4e00,0x000c5000)` |
| Work sector A | `[0x000c5000,0x000c6000)` |
| Work sector B | `[0x000c6000,0x000c7000)` |
| Upper guard block | `[0x000c7000,0x000c7200)` |

Eighteen separate 512-byte `F6 06` operations programmed deterministic,
distinct patterns with exactly one cleared bit in every byte. `F6 18` preceded
every mutation. All non-cut program operations received exact complete-array
post-verification.

The first nine operations prepared the lower guard and sector A. Their exact
checkpoint image was:

```text
ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6
```

After the separately reconciled first block of sector B and the remaining
seven sector-B blocks plus upper guard, the fully prepared image was:

```text
b7b27c2f6fa222fce47a5a2158836665ad2ad951d46b172a4c56215b06e77943
```

## Controlled program checkpoint

The `program-cut` stage first required the exact `prepare-a` image. It wrote a
durable intent, issued `F6 18`, programmed the fixed block at `0x000c6000`,
polled WIP to ready, then deliberately closed without readback. Exit status 4
reported that reconciliation was required.

A new process opened a new loader session and took two complete reads. Both
were byte-identical to the expected postimage:

```text
f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7
```

The classifier reported `exact_postimage_completed`, advanced to
`program_cut_verified`, and recorded `automatic_retry: false`.

## Controlled erase checkpoint

With both work sectors and guards fully prepared, `erase-cut` required image
SHA-256 `b7b27c2f...e77943`, durably published intent, issued:

```text
F6 18
F6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00
```

The loader reported ready, after which the process deliberately closed without
readback. A new process then obtained two complete, byte-identical reads of the
exact expected sector-A-erased image:

```text
ad1b1819bfbfdf0e74774674d3fd915694b231abf7e20808df940d42ef8be27f
```

It again reported `exact_postimage_completed`, advanced to
`work_a_erased_verified`, and did not retry the erase.

## Remaining erase and cleanup

The remaining fixed operations all performed same-session complete-array
post-verification:

| Stage | Erase CDB | Exact postimage SHA-256 |
|---|---|---|
| `erase-b` | `f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00` | `7ca0d0f7fda30174863b378783f49cd97deef941c960772c75e856eee6283ff2` |
| `cleanup-lower` | `f6 15 00 06 20 00 00 00 00 00 00 00 00 00 00 00` | `a2bc397a329164f2740289563f862abe01d221b51a1ffb791ee3564fb50e5bc2` |
| `cleanup-upper` | `f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00` | `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f` |

The final stage removed state only after the complete postimage matched the
original baseline.

## Independent closure

A separately invoked `kb7-isp-verify.py --full-chip` command then read
33,554,432 bytes. It reported the expected V1.22 header/manifest and these
declared/calculated region checksums:

```text
region0: 0xc3f43a6f / 0xc3f43a6f PASS
region1: 0xc8ed2815 / 0xc8ed2815 PASS
region2: 0xaa83e9a3 / 0xaa83e9a3 PASS
```

The final capture SHA-256 was the exact baseline hash
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
The owner then confirmed normal `5038` enumeration and a working keyboard.

## What this proves

For this unit, V1.22 preserved loader, `F6 18` mode, fixed addresses and exact
source plan, the run demonstrates:

- two adjacent fully patterned work sectors and both immediate guards behaved
  exactly as modeled;
- fixed multi-sector program/erase ordering produced every exact checkpoint;
- durable intent preceded each mutation;
- a new host process and USB software session could recover a
  command-complete/no-readback outcome from flash rather than journal authority;
- two exact whole-chip reads distinguished and accepted only the intended
  postimage;
- neither reconciliation automatically replayed its operation; and
- cleanup restored every loader-visible byte of the original 32-MiB image,
  followed by successful normal boot.

## What remains unproven

The run deliberately did not unplug or power-cycle the keyboard while markers
remained. Both controlled commands had finished and WIP was clear before the
host process closed. Therefore it does **not** prove:

- physical USB loss or power loss during CBW/data/CSW, erase, program, or WIP;
- classification or safe repair of arbitrary torn erase/program states;
- safety under disturb, misaddressing, loader bugs, or repeatable same-path
  read defects;
- above-16-MiB mutation, `F6 17` mutation mode, or `F6 19`;
- arbitrary offsets, devices, loaders, flash revisions or update images;
- firmware-region transaction execution, rollback, authenticity or atomicity;
- a return to 5037 from checksum-valid but broken custom core0; or
- any replacement-firmware hardware behavior. No replacement firmware was
  installed or executed.

All byte verification used the preserved loader's `F6 05`/SoC read path. The
separate sessions detect instability but not a repeatable defect in that same
path. External SPI remains the independent recovery route and ordinary-write
recommendation.

## Consequence

The fixed scratch experiment does not need repetition merely to reconfirm this
result. The software updater executor must remain mutation-locked until the
operation transport and proof boundary are re-reviewed. Any future physical
interruption experiment must remain scratch-only, explicitly model torn states,
and retain immediate SPI recovery. Firmware-region execution remains a later,
separately authorized milestone.
