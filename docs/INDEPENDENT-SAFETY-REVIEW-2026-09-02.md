# Independent safety and evidence review of the loader-reentry relock

Review date: 2026-09-02

Reviewed: branch `loader-reentry-proof-hardware-validation` at HEAD
`8908deb0957979e3ea71ebad15a1acea907ee41e` ("Relock loader proof pending USB
read reliability"), compared with its direct ancestor
`63580288dc24d76af1f5d976e469698907e6e8e3`. The review was offline and
read-only: no hardware was operated, no USB device was opened, no commit-mode
tool ran, and no tracked file was modified during the review. Builds and tests
were limited to host-only suites. No ARM cross-compiler was available in the
review environment, so the recovery-proof ELF and trampoline blob hashes could
not be re-derived.

## 1. Final verdict

**CLEAN WITH NON-BLOCKING NOTES.**

The fixed read-only USB read-reliability sweep is safe to run as designed.
Nothing in the tree authorizes proof installation. The notes below are real
defects in gate placement, evidence labelling and tests, but none of them makes
the read-only experiment unsafe.

## 2. Blocking findings

None.

## 3. Non-blocking findings, ranked

### N1 (High, gate placement) — the relock lives only in the CLI, not in the mutation path

`require_live_authorization` and `require_read_only_preflight_authorization`
(`tools/flash-access/kb7-loader-reentry-executor.py:290-301`) are called only
from `main()` at lines 1340 and 1345. `live_step` (line 1091) and
`FixedProofMutationBackend.execute` (line 911) emit `F6 18` / `F6 06` / `F6 15`
with no gate, and the production test at
`pc_app/tests/test_loader_reentry_executor.py:478-522` drives that backend to a
program event with the gates False. A short Python script importing the module,
holding the private campaign artifacts and a journal in `boundary_verified`
state, could mutate flash without editing any pinned source.

Consequence: the incident record's sentence "The loader-reentry executor cannot
open USB or mutate flash" (`docs/USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md:79`)
and the README's "both its USB preflight and mutation paths are hard-disabled"
are true of the CLI only.

Correction: call the gate inside the backend constructors before
`device_factory()` (lines 898 and 949); add a test that constructing each
backend with the gate False raises `ExecutionLocked` before any device opens;
reword the two sentences to "the executor CLI". This must be fixed before any
reauthorization review.

### N2 (High, evidence) — programmer state during the 2026-08-31 USB sessions is not recorded

`tools/flash-access/README.md:19-38` attributes earlier USB read errors and boot
glitches to an unpowered ESP32 clamping the flash bus. Neither the incident
document nor the JSON incident block states whether the programmer was
physically disconnected during the `25f1…` preflight and the `e71b…` capture.
If it was attached, the `e71b…` failure may have the already-known cause and the
sweep tests the wrong hypothesis.

Correction: add an explicit per-session field, and record it for the sweep run
too.

### N3 (High, evidence) — the 2-byte change has no stated cause window, and one JSON string asserts a mechanism

No document names a cause, which is correct. But
`hardware/kb7-stock-loader-reentry.json:300` says the bytes were "programmed to
zero"; `0x80` to `0x00` and `0xff` to `0x00` are one-way clears consistent with
a program or a cell-loss event, so "cleared" is the defensible word. The last
SPI-exact state was 2026-08-24; nothing records what sessions or boots occurred
before the 2026-08-31 discovery.

Correction: state "cause not established", list the candidates, and bound the
window.

### N4 (Medium, stale statements)

- `docs/OPEN-SOURCE-REVIEW.md:117-119` still says the fixed proof executor "is
  live only for that exact bounded install/restore test", contradicting lines
  43-50 of the same file and every other document.
- The executor docstring (`tools/flash-access/kb7-loader-reentry-executor.py:12-13`,
  visible in `--help`) says the same and is hash-pinned, so fixing it requires a
  re-pin.
- `tools/flash-access/kb7-enter-isp.py:10` still directs operators to "run
  kb7-isp-verify.py directly".

### N5 (Medium, test defect) — the dry-run "USB opened" trap cannot fire

In `pc_app/tests/test_isp_read_reliability.py:201-206` the trap patches the
module attribute, but `run_live` binds `NoRecoveryReadOnlyDevice` as a keyword
default at definition time (`tools/flash-access/kb7-isp-repeat.py:268-269`), so
the patched attribute is never consulted. The test passes only because dry-run
returns before `run_live`. On a libusb host with a keyboard attached, a
regression that opened USB in dry-run would open it for real.

Correction: resolve the factory at call time and add a `--commit` variant
asserting the trap fires.

### N6 (Medium, public-tree checker) — two destructive tools' state files are not denied

`tools/check_public_tree.py` denies the read-reliability result schema (new,
lines 60-62 and 135-137) but still does not deny
`.kb7-isp-write2-state.json`, `.kb7-isp-erase-granularity-state.json`, their
schemas (`kb7-isp-write2-state-v3`, `kb7-isp-erase-granularity-state-v1`), or
the executors' randomized temp-journal names. Confirmed by running the checker
on synthetic files. Contents are hashes and USB topology, so exposure is low,
but the stated policy is not met.

### N7 (Medium, SPI recovery instructions)

The unpowered-programmer hazard, reset hold, flashrom verify, independent read
and cold-boot check are all documented. Gaps:

- the full-chip restore power sequence is described as "the sequence used for
  the rehearsal" without being written down;
- `tools/flash-access/SCRATCH-RESTART-TEST-PLAN.md:141-146` never says when
  keyboard USB power is re-applied, while the read scripts require it for the
  flash rail;
- the proof runbook does not link the full-chip restore command.

Correction: one canonical restore section (power off, clip, hold reset, apply
board USB power, programmer power, write, verify, independent read, power off,
disconnect, cold boot, `10f5:5038`) linked from every runbook.

### N8 (Medium, static proof) — the relocation routine is digest-pinned, not decoded

`tools/verify_loader_reentry.py:523-560` does not decode the 88-byte relocation
routine. It checks a pinned digest plus three literals and then emits
`copy_bytes` and reset-write facts as constants. The fixture in
`pc_app/tests/test_loader_reentry.py:206-214` fills that body with
pseudo-random bytes and the chain still passes.
`docs/STOCK-LOADER-REENTRY-2026-08-23.md:35-38` overstates this as verified
"relocation semantics".

### N9 (Medium, proof-image design) — a relocation fault recurses into lockup

In the proof build, `kb7_fault_capture` ends in `kb7_enter_loader`
(`replacement_fw/drivers/recovery.c:70`), which re-runs
`kb7_reenter_preserved_loader` (line 94). A fault during relocation, such as an
early XIP read at `0x60001000` in the ROM-default clock state, recurses inside
HardFault into lockup with both watchdogs disabled. Every cold boot would repeat
it, leaving external SPI as the only exit.

Correction: park on fault in the proof profile.

### N10 (Low, evidence labelling)

- Mailbox retention across `SYSRESETREQ` is inferred from the stock consumer,
  not a datasheet fact; the JSON labels the whole block `firmware_recovery`.
- `hardware_validation` now conflates the 2026-08-24 stop (phase unknown,
  `old_preflight_root_cause_known: false`) with the 2026-08-31 stop by flipping
  `read_only_preflight_exact_failure_phase_observed` to true.
- The `e71b…` capture's region-2 CRC failure is not independent evidence, since
  the pre-repair stock capture itself fails region 2
  (`hardware/kb7-stock-flash.json` manifest entry 2); the byte-diff evidence
  stands on its own.

### N11 (Low, tool semantics and exit codes)

- `F6 17` sets the NOR's volatile 4-byte address mode; the tool is read-only for
  array contents but does change device state, and the docs should say so.
- The transport whitelist also admits `F6 01` (never emitted).
- Exit codes 0/1/2/3 are documented only in the JSON, and argparse errors share
  code 2 with pin-mismatch stops.
- The sweep's identity check pins the `F6 00` identity and fixed `F6 F1` fields
  but not the loader fingerprint `99e75493…` that the executor's preflight pins.

### N12 (Low, test coverage)

- No test drives short reads, non-zero CSW status, wrong loader identity,
  `KeyboardInterrupt` mid-sweep, or the pin check preceding device open under
  `--commit` (every `main()` test mocks `require_reviewed_tool`).
- No CLI test asserts `step`, `validate-reentry` or `finalize --commit` are
  refused.
- No host test transfer crosses a 4 KiB sector.
- `pc_app/tests/test_recovery_trampoline.py:125-137` asserts a Python loop
  against itself.

### N13 (Low, uncorroborated constants)

`KB7_REGION1_COPY_BYTES = 0xde000` and the OPI source `0x30722000` in
`replacement_fw/include/kb7/regs.h` exceed the manifest's region-1 length and
appear in no recovered-offset record. Not on the proof path.

## 4. What the hardware evidence establishes

- The 32 MiB baseline `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`
  is the pinned identity in 55 consistent places and is corroborated by three
  independent SPI reads. The baseline file originated as a USB capture; the SPI
  corroboration is what makes it trustworthy.
- The `25f1bb67fb2c6d40319edaf45fce1f1f70e4829474160116a0ab1d26c8b5d205`
  preflight image differed from the baseline by exactly two bytes at
  `0x00040000-0x00040001` inside stock Core 1 (region 1, runtime `0x1001f000`),
  outside the header, loader, manifest and the proof's mutation domain. An
  independent SPI read reproduced the same full-chip hash. That is confirmed
  physical NOR corruption, and the docs never treat it as a USB artifact.
- External SPI restored the baseline; flashrom verify and a separate SPI read
  matched `2b1472…`; the keyboard booted as `10f5:5038`. Confirmed as recorded.
- The later USB capture `e71b622cf2978a39271696048e5c7ccc1b5de91b4449d855b5637865ac0bb86b`
  is internally consistent as a read-path failure: page counts add up, every
  bad page is command-aligned, and the first bad page `0x00015000` lies in
  region 0 so all three CRC failures follow. Every statement about it is
  qualified as "not an image of the physical NOR". No conclusion in the tree
  rests solely on that capture. Which layer failed is a reasonable inference,
  not a proof.
- The relock is real at the CLI and policy layers: both constants are False,
  the test suite fails if either flips, the source audit requires the False
  literals, and the hardware-facts checker pins the JSON gates and all four
  hashes.

## 5. Claims that remain unproved

- The cause and timing of the `0x00040000` change.
- Whether the external programmer was attached during either 2026-08-31 USB
  session.
- Which component produced the `e71b…` corruption and whether it reproduces.
- Physical NOR state after the `e71b…` session (only a boot check, no SPI read).
- That a passing sweep (400 commands over five ranges) implies a reliable
  8,192-command full-chip read.
- Mailbox survival across `SYSRESETREQ`, early XIP readability before clock
  init, and that the loader's updater path enumerates as `10f5:5037` after
  consuming the marker.
- The proof image identity (`dde05f…`, 1,228 bytes) and trampoline blob hashes,
  which need an ARM toolchain absent in the review environment.
- The 2026-08-24 first-stop root cause.

## 6. Commands run and results

```
git fetch origin loader-reentry-proof-hardware-validation      -> 8908deb0957979e3ea71ebad15a1acea907ee41e
git merge-base --is-ancestor 63580288 8908deb                  -> yes (one commit)
git diff --check 63580288 HEAD                                 -> clean
git diff --stat 63580288 HEAD                                  -> 23 files, +1095 -285
PYTHONPATH=pc_app python3 -m unittest discover -s pc_app/tests -> 274 tests, 1 error
   (test_recovery_trampoline.test_trampoline_is_exact_self_contained_thumb_blob:
    arm-none-eabi-gcc not installed in the review environment; environmental)
unittest test_loader_reentry_campaign test_loader_reentry_executor
         test_isp_read_reliability                             -> 50 tests OK (matches JSON pin of 50)
python3 tools/check_public_tree.py .                           -> passed, 208 files
   (also passed on a clean git-archive export of HEAD)
python3 tools/check_hardware_facts.py                          -> pass
python3 tools/audit_firmware_source.py .                       -> pass
JSON validation of all 6 tracked .json files                   -> ok
Markdown relative-link validation, 44 files                    -> 0 problems
node --check pc_app/web/app.js && node validation-test.js      -> ok
recomputed pins: plan b1f80b21… MATCH, tool descriptor c38b3ee1… MATCH,
   verifier source 9b19d393… MATCH, executor descriptor ef17000a… MATCH,
   policy 2f2e46ae… MATCH, implementation hashes (campaign 085dd0…,
   planner 618bed…, verifier 9b19d3…, writer f706cb…) MATCH
gcc -fsyntax-only recovery.c/startup.c with proof gates        -> ok; without the
   explicit unverified gate the build fails at config.h:29 as designed
```

Not verifiable offline: image hashes `2b1472…`, `25f1bb…`, `e71b62…`, campaign
ID `3fa076…`, proof image hashes, loader fingerprint `99e754…`, and all region
CRCs.

## 7. Branch state and file hashes

Branch `loader-reentry-proof-hardware-validation`, HEAD
`8908deb0957979e3ea71ebad15a1acea907ee41e`, worktree clean during review.

| File | SHA-256 |
|---|---|
| `tools/flash-access/kb7-isp-repeat.py` | `27d85c69e902c3059f046dfb1862c30b572c94b1dd9020d97ec69755bca097a9` |
| `tools/flash-access/kb7-loader-reentry-executor.py` | `396a60bfa11b007d97328bcf62dc08a6c9e31a5f99ee3a84ab8b3dc8ae332992` |
| `tools/flash-access/kb7-loader-reentry-campaign.py` | `085dd0c2087e258d880824f657e37ecde08f4fd05234ab14d948af245d8de765` |
| `tools/flash-access/kb7-isp-verify.py` | `9b19d393cf64c66168e08de2f3d4fe352a85a2fd69545e374dee0fa015dea338` |
| `pc_app/tests/test_isp_read_reliability.py` | `0ba841ecf9cedf2bb500dd0e64f8e76c5b8ed19c4e23732b52c544764dce9e6f` |
| `pc_app/tests/test_loader_reentry_executor.py` | `44cb41a3869560083613fc887ff5bc11ba160633d35416daeec81d33cfbfbc1e` |
| `hardware/kb7-stock-flash.json` | `fc150dec48a114aba191263e07704cfbc8da8a5047bbd3bf4acd55b6a1755685` |
| `hardware/kb7-stock-loader-reentry.json` | `388aeb7e3c41eec04e7f47b75fb7e5c62e6434d4794bd43373f3dc32c6833945` |
| `tools/check_hardware_facts.py` | `2caf5c444f9970133bf33752f5c1afcc897b9cb111d67f0a31d256ca21885856` |
| `tools/check_public_tree.py` | `ef57119d157f3553facc2a997031ce1ea60e2935f7ad2570f4358957f047a963` |
| `docs/USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md` | `3902c71e4a07fded21cc1c8c72025bfb5f3e1257f7ab22102d77bd729f72a990` |

## 8. Is it safe to proceed with the fixed read-only USB reliability experiment?

Yes, with two operator conditions.

Traced through production code: every CDB passes the verifier's whitelist
`{F6 00, F6 01, F6 05, F6 17, F6 F1}` before any transfer, the CBW never carries
a data-OUT phase, opcodes are literals, and no argv, environment, file or state
content reaches a CDB byte. The plan is `FIXED_RANGES × FIXED_CHUNKS ×
FIXED_PASSES` and is hash-bound three ways (descriptor, plan, verifier source),
checked at `main()` line 324 before the reference is even loaded.
Stable-but-wrong, unstable, short-read, CSW-status, identity, factory-open,
mid-sweep interrupt and strict-close failures all end in exit 1 or 3 without
printing PASS, and a failed session sends no clear-halt, release, reattach or
later command. The tool writes no state file, and nothing in the tree reads its
output as authorization.

Conditions:

1. Physically disconnect the external programmer before the run and record
   that fact.
2. Power-cycle before any later attempt after an exit-3 stop, as the tool
   itself instructs.

## 9. Does anything currently authorize installing the loader-reentry proof image?

No.

Both executor constants are False, the policy descriptor and hardware JSON say
so, and the checker, source audit and executor tests would all fail if they
changed. Installing requires editing `LIVE_PROOF_CAMPAIGN_ENABLED`, re-pinning
the executor descriptor and policy hashes, updating the JSON and its checker,
and passing a separate review. A sweep pass authorizes, per code and every
document, only review of a preflight-only revision.

The one caveat is N1: the prohibition is enforced by the CLI and by pins, not
inside the mutation backend, so the correct statement is "the executor CLI
cannot mutate", and that gap should be closed before the reauthorization
review.
