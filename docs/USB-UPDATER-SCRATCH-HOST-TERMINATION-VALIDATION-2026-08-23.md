# Fixed scratch host-termination hardware validation — 2026-08-23

## Result

The owner completed one end-to-end run of the fixed v3 scratch-only executor
on the development KB7. The exact hash-bound plan was:

```text
c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653
```

The mandatory boundary-9 step completed and validated the fixed `program-09`
BOT transaction, durably published and read back
`checkpoint_command_complete`, and then terminated its own process with signal
9. Fish reported status 137. The killed process did not poll WIP, read flash,
publish boundary 10 or explicitly close USB.

A fresh process used the mutation-incapable reconciliation backend, completed
the omitted WIP-ready poll, took two exact full-chip reads and classified the
image as the expected boundary-10 postimage without replay. The remaining fixed
scratch operations restored the complete baseline. Final read-only
reconciliation verified boundary 22 twice and cleared the journal. A separate
post-cycle verifier capture matched the 32-MiB baseline byte-for-byte and all
three manifest-region CRCs passed. After a cold boot, the owner confirmed
`10f5:5038` enumeration and normal keyboard operation.

The general paired-firmware executor remains mutation-locked, no firmware
region was touched, no custom firmware was booted, and `flash_approved=false`.

## Bound inputs and fixed checkpoint

| Field | Observed or enforced value |
|---|---|
| Device/loader scope | one development unit, preserved V1.22 loader |
| Manifest header version | `v1.0.00` |
| Loader-window SHA-256 | `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56` |
| Baseline size | 33,554,432 bytes |
| Baseline SHA-256 | `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f` |
| Scratch envelope | `[0x000c0000,0x00100000)` |
| Operation set | 18 fixed programs and four fixed erases |
| Checkpoint operation | `program-09`, boundary 9 to expected boundary 10 |
| Offset and length | `0x000c6000`, 512 bytes |
| Program CDB | `f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00` |
| Payload SHA-256 | `ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380` |
| Boundary-9 SHA-256 | `ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6` |
| Boundary-10 SHA-256 | `f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7` |
| Termination | self-`SIGKILL`, signal 9; operator-observed shell status 137 |

Committed preflight accepted two byte-identical owner baselines and classified
the live image as `exact_stock_or_complete` at boundary 0. Nine separate
ordinary steps then reached boundary 9, where the observed whole-image hash was
the exact expected preimage above.

The checkpoint command followed the fixed policy
`after_validated_program_csw_before_wip_poll_or_postread`. Raw intent was
durable before backend construction or USB. The address-mode command and the
complete 512-byte program exchange succeeded with a strictly validated CSW.
The executor locally abandoned the handle, atomically published and read back
the command-complete state, and self-signalled. Status 137 is console evidence;
it is intentionally not encoded in or recoverable from the journal.

The owner accidentally invoked committed `step` once more after the killed
process. This exercised a useful negative gate: the exact command-complete
journal caused the second invocation to return reconciliation-required status
4 before opening USB or replaying the command. A following local-only `inspect`
reported `checkpoint_command_complete`, boundary 9 and `usb_opened=false`.

## Fresh-process reconciliation and closure

Dry reconciliation first validated the exact command-complete state without
opening USB. Committed reconciliation then consumed the one-shot state before
opening the mutation-incapable backend. It completed the omitted WIP poll and
accepted two identical full-chip reads as:

```text
classification : exact_postimage_completed
boundary       : 10
observed SHA-256: f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7
next operation : program-10
automatic retry: false
```

The command was not replayed. The remaining twelve state-derived operations
reached boundary 22 with classification
`exact_baseline_restored_pending_finalize` and the original baseline hash.
Final reconciliation in another process took two exact reads, classified
`exact_stock_or_complete`, reported no active-intent WIP poll, and cleared the
journal.

The separate post-cycle verifier saved a 33,554,432-byte capture with the exact
baseline SHA-256. Its region results were:

| Region | Declared | Computed | Result |
|---:|---:|---:|---|
| 0 | `0xc3f43a6f` | `0xc3f43a6f` | pass |
| 1 | `0xc8ed2815` | `0xc8ed2815` | pass |
| 2 | `0xaa83e9a3` | `0xaa83e9a3` | pass |

That verifier is a separate invocation, but it and executor reconciliation
both use the preserved loader and SoC `F6 05` flash-controller path. This is
not independent electrical verification. The raw images, journal, complete
transcript and owner-local paths remain outside the public repository.

## Proof boundary

This one-unit result demonstrates that the fixed program BOT transaction and
validated CSW completed, the exact command-complete state became durable, the
userspace process then died by signal 9 without a same-session WIP poll or
postread, and a fresh read-only process classified the exact postimage without
replay. It also demonstrates exact fixed-plan cleanup and return to normal stock
operation on this unit.

It does **not** show that WIP was busy when the signal arrived. Journal `fsync`
and readback add an unmeasured interval between CSW and termination. It does not
interrupt a CBW, data-OUT, CSW or NOR program pulse; disconnect USB; remove
device power; test an erase interruption; demonstrate arbitrary torn-NOR
recovery; exercise `F6 19` or mutation above 16 MiB; touch firmware regions; or
validate a general/production updater. External SPI remains the independent
verification and recovery path.

The exact procedure and stop rules remain in the
[v3 host-termination test plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md).
