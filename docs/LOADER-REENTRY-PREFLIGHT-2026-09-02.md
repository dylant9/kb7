# Loader-reentry read-only preflight, 2026-09-02

Date: 2026-09-02. Branch `loader-reentry-preflight-only` at `7c3d5a4`
(executor source `f7a684d75173afb16486c36f61eafb57fe1a194c127cfd95ea1a235c6bffc45a`),
campaign `113897c215c88a1aea2e483601a968b88e2686fad2df5c6752cb66276d9f43e2`,
after the read-reliability gate pass and the independent follow-up review
verdict CLEAN WITH NON-BLOCKING NOTES.

## Result

Exit 6, `READ-ONLY PREFLIGHT VERIFICATION STOPPED` at
`exact_baseline_verification`. Two complete 32 MiB reads through the loader
finished, were identical to each other, and differed from the reviewed baseline
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f` in exactly
one contiguous range, 434 bytes at `0x01a0d6e6-0x01a0d897`, giving image
SHA-256 `35968ec55f16c64fcdca72a6c39edb9b563e5e466657dce67827dc63149566fa`. No
program or erase command is representable in that transport; the interface was
left unbound and no further USB command was issued in that powered session.
The journal stayed at `preflight_started`, bound to the executor source above.

Two further read-only full-chip captures in a later powered session, each in
its own USB session, reproduced the same image hash and passed all three
manifest region checksums, each read taking under ten seconds. That is four
consistent full-chip reads through the loader on this day.

## What the difference is

- Every byte below the manifest-declared image end `0x0156af8c` (header,
  loader, manifest, Core 0, Core 1, assets) is identical to the baseline.
- The stock settings store occupies fourteen 4 KiB sectors from `0x01a00000`;
  exactly one, `0x01a0d000`, differs. Inside it one settings record kept its
  header, had its 432-byte payload rewritten with a constant fill and its
  two-byte trailer updated. Bits changed in both directions, so the firmware
  erased and rewrote that sector and restored every other byte in it exactly.
- The range is not 512-byte aligned and is not the zero, `0xff` or half-address
  acquisition signature. It is ordinary stock-firmware settings activity, most
  likely following normal use of the keyboard after the last SPI restore.
- The space between the image end and `0x01a00000` also holds data in both
  images.

## Conditions

External programmer physically detached; NOR lead stubs at ~20 mm; bare
motherboard; one `10f5:503d` hub and one keyboard on the bus; no mass-storage
mount; ISP entered by the vendor HID mode-switch. A first launch of the
committed run was stopped by the host session about 30 seconds in, before the
executor had opened the device: its log was empty, no journal existed and
usb-storage still owned the interface. The run was relaunched detached from the
session and completed.

## Consequence

The exact-full-chip model cannot survive ordinary use of the keyboard: every
stock settings write breaks the baseline. The executor now treats everything
from the sector after the image end to the end of flash as a post-image live
region: recorded in the journal, required stable within each operation and
across the proof boot, but never required to equal the reviewed baseline. The
region below it remains byte-exact against the modelled boundary images. See
the policy descriptor and `hardware/kb7-stock-loader-reentry.json`.

Authorization is unchanged: both proof gates are false on the
hardware-validation branch.

## Pass under the live-region policy (2026-09-03)

After the live-region policy, the F1 proof-startup change with its campaign
regeneration (campaign `1ce62e95ee2c6c84b5abb8996f7964bacae661869152ead20f5c7138b2b0b508`)
and a second independent review (CLEAN WITH NON-BLOCKING NOTES), the rebuilt
preflight-only branch (executor source
`12dd876ac6964b8c3ef4675ed69664a205d663ea65961a560a2ecc8acb2b2db5`) ran the
read-only preflight again under the same physical conditions. Exit 0: two
identical full reads, byte-exact below `0x0156b000` against the baseline,
observed full image still `35968ec55f16c64fcdca72a6c39edb9b563e5e466657dce67827dc63149566fa`,
live region recorded as
`04b21e7889e26171b3d2b338554672faa3f86a40e550d566a89f2eafa67d70b4`, loader
fingerprint `99e75493ef2f627b072560ef7ee45f3c01648eca715ce03a4001727eace9e7c6`,
device path 3-2.2 at USB address 24, strict close with kernel-driver
reattachment, journal `boundary_verified` at index 0, and normal `10f5:5038`
operation after a power-cycle. That journal is bound to that executor source;
any later revision runs its own preflight.
