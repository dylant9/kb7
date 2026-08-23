# Mandatory active-intent checkpoint test plan — 2026-08-23

> **Historical v2 plan.** This exact plan completed successfully and remains
> the evidence record for the command-complete/WIP-ready/no-postread
> checkpoint. The current source uses the subsequently hardware-validated v3
> self-`SIGKILL` checkpoint documented in the
> [host-termination test plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md)
> and [v3 validation record](USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md).

## Status

**Completed successfully on the development KB7.** The historical
`kb7-updater-scratch-executor.py` source retains the same 18 fixed programs and
four fixed erases as the earlier executor, but its v2 plan makes one
active-intent checkpoint a mandatory part of execution. That safety policy is
included in the plan descriptor and journal schema rather than treated as an
operator-selected fault-injection option. See the
[v2 hardware validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md)
for the observed hashes, state transitions and proof limits.

The preceding v1 executor plan, SHA-256
`491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`,
completed one hardware cycle and restored the exact baseline. That result is
historical evidence for the unchanged command set and geometry. It is not a
hardware result for the current v3 source or its post-CSW host-termination
state machine.

That v2 plan descriptor, including the mandatory checkpoint,
single-attempt rule and exact-preimage stop policy, has SHA-256
`f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32`.

This remains a destructive, dry-run-default laboratory harness. It cannot
accept a firmware bundle or a caller-selected address, operation, CDB, payload,
device, retry, force or skip. The paired-firmware executor remains read-only,
replacement-firmware mutation remains unavailable, and
`flash_approved=false`.

## Fixed checkpoint

The first nine ordinary `step` invocations move the transaction from boundary
0 through boundary 9. At boundary 9 the next ordinary `step` is unconditionally
the reviewed checkpoint operation:

| Field | Fixed value |
|---|---|
| Operation | `program-09` |
| Transition | boundary 9 to expected boundary 10 |
| Flash offset | `0x000c6000` |
| Length | 512 bytes |
| Address mode | `F6 18` immediately before the program |
| Program CDB | `f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00` |
| Payload SHA-256 | `ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380` |
| Operation-descriptor SHA-256 | `dbba0199b94c9ee3fd8d50c9aaac37f33acead94d8ac299a793c3cc7f53d5455` |

There is no checkpoint flag and no normal-step bypass at that boundary. The
step obtains two exact preimage reads, durably publishes its canonical intent,
issues `F6 18` and the fixed `F6 06`, and waits until the strict WIP poll reports
ready. It then deliberately performs **no postread**, leaves the intent active,
closes the USB session while holding the same journal lock, and exits 4. The
next permitted action is read-only reconciliation from a fresh Python process.

This is a controlled **command-complete/no-readback** checkpoint. It does not
disconnect USB during CBW, data, CSW or WIP, interrupt a NOR program pulse, or
remove device power.

For the previously validated baseline SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`,
the exact complete-image hashes around the checkpoint are:

```text
boundary 9 preimage : ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6
boundary 10 postimage: f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7
```

A different accepted owner baseline produces different complete-image hashes;
the executor derives and binds them before opening USB. Do not substitute a
different baseline during one journaled transaction.

## Read-only and process boundaries

Committed preflight and reconciliation instantiate the verifier's read-only
USB transport. Its whitelist can represent loader identity, status, `F6 05`
reads and the nonpersistent `F6 17` read-address mode, but not `F6 06`, `F6 15`,
`F6 18`, `F6 19` or a data-OUT program phase.

Every active intent records a random process-instance nonce. Reconciliation
refuses the same process instance before opening USB. A new CLI invocation
therefore creates both a new Python process and a new read-only libusb/BOT
session; it takes two byte-identical 32-MiB reads and never retries a command.

At the mandatory checkpoint:

- exact postimage produces `exact_postimage_completed`, advances to boundary
  10 and selects `program-10` for a later process;
- exact preimage is a known, non-corrupt outcome but consumes the plan's single
  checkpoint attempt. Reconciliation durably records `checkpoint_no_effect`,
  exits 5 and blocks every later `step`; stop and retain that exact scratch
  state and journal pending a separately reviewed cleanup decision rather than
  retrying, deleting state or power-cycling;
- a stable image other than the exact preimage or postimage requires external
  SPI recovery; and
- unstable or incomplete reads leave the intent unresolved. Do not infer an
  outcome and do not issue another USB mutation.

## Hardware sequence

The completed experiment used the following guarded sequence. Any separately
authorized repeat must use two distinct, byte-identical owner captures, the
reviewed V1.22 loader, the erased `[0x000c0000,0x00100000)` containment
envelope, and a new owner-local v2 journal. Keep the rehearsed 3.3-V external
SPI recovery path immediately available and physically disconnect any
unpowered programmer from the flash bus during USB operation.

1. Run the repository checks and inspect the v2 plan hash printed by a dry run.
2. Run committed read-only `preflight`. It must classify exact boundary 0 and
   create a new journal.
3. Run nine separate committed `step` processes. They must complete only
   `program-00` through `program-08` and reach boundary 9.
4. Run a dry `step`. It must identify `program-09` and print the mandatory
   `after_command_and_wip_poll_before_postread` policy without opening USB.
5. Run that `step --commit`. It must issue one command, report no postread,
   leave an active intent at boundary 9 and exit 4.
6. Start a new process and run `reconcile --commit`. The expected result is the
   exact boundary-10 postimage, `automatic_retry=false`, and `program-10` as the
   next operation. Exit 5 with `checkpoint_no_effect` means the exact preimage
   remains; stop the campaign and preserve the journal and known image for a
   separately reviewed cleanup decision. Do not retry, delete the journal or
   power-cycle. Stop on every other outcome.
7. Run the remaining twelve state-derived steps, `program-10` through
   `erase-upper-guard`, one process at a time. The later established checkpoint
   hashes for the baseline above are:

   ```text
   boundary 18: b7b27c2f6fa222fce47a5a2158836665ad2ad951d46b172a4c56215b06e77943
   boundary 19: ad1b1819bfbfdf0e74774674d3fd915694b231abf7e20808df940d42ef8be27f
   boundary 20: 7ca0d0f7fda30174863b378783f49cd97deef941c960772c75e856eee6283ff2
   boundary 21: a2bc397a329164f2740289563f862abe01d221b51a1ffb791ee3564fb50e5bc2
   boundary 22: 2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f
   ```

8. Run final read-only reconciliation from another process. It must verify the
   exact baseline twice and clear the journal.
9. Use the separate read-only verifier entry point for one final complete
   capture and exact comparison, then power-cycle and confirm normal operation.

Do not automate past exit 4 or any unexpected status. Preserve the complete
console output outside the public repository for later evidence review.

## What the completed run proves

For one unit, loader, baseline and tested v2 plan/checkout, the completed run
shows that:

- the executor itself durably publishes the fixed active intent before its
  mutation;
- the fixed command completes and reaches WIP-ready without same-session
  postread or boundary publication;
- a genuinely fresh process using a mutation-incapable transport classifies
  the exact postimage from flash rather than journal authority;
- reconciliation does not replay the operation and normal state-derived
  execution can continue from boundary 10; and
- the fixed cleanup returns every loader-visible byte to the baseline.

It does not prove safety under a physical cable removal, host or device power
loss, a torn program or erase pulse, disturb, device-side misaddressing, another
loader or flash revision, `F6 17`/`F6 19` mutation, firmware-region writes,
replacement-firmware correctness, or a production updater. Both executor and
verifier reads still use the same preserved-loader/SoC flash-controller path;
external SPI remains the independent verification and recovery route.
