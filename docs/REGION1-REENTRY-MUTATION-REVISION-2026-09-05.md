# Region-1 mutation-enabled revision

Branch `region1-reentry-mutation-enabled`, built 2026-09-05 on top of the
preflight-only branch after its read-only preflight passed
([record](REGION1-REENTRY-PREFLIGHT-2026-09-05.md): journal
`boundary_verified` 0, live region `04b21e78…`, observed full image
`35968ec5…`).

## What this revision enables

`LIVE_PROOF_CAMPAIGN_ENABLED = True` in addition to the read-only preflight,
for the exact reviewed campaign
`9a582f1cf35ccb219d5477299ece6caa1285fcbff448e7901fdcaaae83e5c267`
(proof raw `e753380b…`, 404 bytes at the stock region-1 entry; proof full
image `f5ff8321…`). Every other campaign identity, any pin drift and the
general paired-firmware executor stay refused in the CLI, every live entry
point and both USB backends; `flash_approved` stays false.
Pins: policy `c5a7d7f37009d562a196caec34fb03c3df70183e11cfaa5d38e358bd8ac6f33b`,
executor descriptor `27a04ad46617feab56b77a2dd82707eeb8f7eef1a3d07f1b5a54e6fa95363952`,
executor source `ba487415d24a0af4cdbf05116ba3592a890a3f1005eaabae34d503aee3477632`.

The 40 operations are the campaign's: 20 install (poison the stock sector
`0x00022000`, rebuild the patch sector `0x0006b000` with its gate erased,
restore the poison sector, program the gate) and 20 restore back to the
exact stock baseline. Region 0, the header, the loader, the manifest and
everything after region 1 have zero operations. Each committed `step`
publishes a terminal intent, takes two exact full-chip reads, executes
exactly one operation, takes two exact reads, closes strictly and only then
publishes the next boundary. Every read is byte-exact against the modelled
boundary image below `0x0156b000`; the live region above it must equal the
value recorded at the previous boundary.

## Prerequisites, sequence and stop rules

The [region-1 runbook](REGION1-REENTRY-RUNBOOK-2026-09-05.md) is normative.
Points specific to this revision:

- A fresh journal path: the preflight-only journal binds executor source
  `f59ca0b0…` and is refused here. The session therefore starts with its
  own `preflight --commit`.
- Run every `--commit` as a transient root service
  (`sudo systemd-run --unit … --collect --property=WorkingDirectory=… \
  --setenv=PYTHONDONTWRITEBYTECODE=1 /bin/sh -c '… > log 2>&1; echo
  exit=$? >> log'`) and poll the log. Terminal-attached or background-shell
  launches were killed mid-run in earlier sessions; a hang-up after an
  intent is an exit 3.
- Expect an exit 3 as a plausible outcome, not an emergency: about 160
  full-chip reads, any single wrong read after an intent is terminal, and
  the answer is the full-chip SPI restore in `tools/flash-access/README.md`
  followed by a restart from step 0 with a new journal.
- The proof boot carries stock region 0's own failure path: a read fault
  during the region-1 copy trips its first-word check and parks the unit
  with a persistent-record attempt aimed at header offsets `0x800..0xbff`.
  The header is compared byte-exact at every later read, so any such write
  ends the campaign with exit 3 rather than being missed.
- Before `validate-reentry`, read `/sys/bus/usb/devices/3-2.2/idProduct`
  (`5037`) and `devnum` passively and compare `devnum` with the journal's
  `current_usb_address`; if equal, power-cycle again first.

## Proof boundary

A pass proves that one checksum-valid custom region 1, running under the
untouched stock region 0 from the DRAM-backed aperture, deliberately
returns to the untouched stock USB loader, and that the fixed campaign
installs and removes it through the loader alone. It does not prove
recovery from a region 1 whose entry never reaches the takeover, from code
that damages clocks or peripherals first, or from a physically damaged
flash; external SPI remains the final recovery route for those.
