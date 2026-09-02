# USB-ISP read-reliability incident

Date: 2026-08-31

## Result

The fixed loader-reentry proof was **not installed**. Its committed preflight
was read-only and sent no program or erase command, but it found a stable
two-byte difference from the reviewed stock baseline. An independent external-
SPI read reproduced the same complete-image SHA-256, proving that this first
observation was real physical NOR state rather than a USB acquisition error.

The two differing bytes were the complete half-open range
`[0x00040000,0x00040002)`: expected `80 ff`, observed `00 00`. The observed
32-MiB image had SHA-256
`25f1bb67fb2c6d40319edaf45fce1f1f70e4829474160116a0ab1d26c8b5d205`.
Regions 0 and 2 still matched their declared checksums, while Region 1 computed
`0xcd464c45` instead of declared `0xc8ed2815`. The one-way bit loss was in the
stock Core-1 executable region. It was therefore a stop condition regardless
of its origin.

The owner restored the complete reviewed baseline through the rehearsed
external-SPI path. Flashrom verified the write, and a separate full external-
SPI read was byte-identical to the baseline with SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
The keyboard then cold-booted as `10f5:5038` and worked normally.

## Separate post-restore USB acquisition failure

After that exact SPI restoration and working stock boot, the owner deliberately
returned the keyboard to `10f5:5037` and saved another 32-MiB read through the
preserved loader. That USB capture had SHA-256
`e71b622cf2978a39271696048e5c7ccc1b5de91b4449d855b5637865ac0bb86b`
and was not an image of the physical NOR:

- 2,031,715 bytes differed from the exact baseline;
- 7,634 of 8,192 4-KiB pages were exact and 558 were wrong;
- every wrong page began on the 4-KiB boundary of one `F6 05` request;
- 194 wrong pages were all zero and 40 were all `ff`; and
- at least 88 nonuniform wrong pages exactly reproduced baseline data from
  one-half of the requested address, including low and high flash addresses.

The three computed region checksums were `0x3be332fc`, `0x89cb434b` and
`0x0741feb9`; all differed from the declarations. The board subsequently
returned to a working `10f5:5038` boot. The page alignment, fabricated constant
pages and exact half-address substitutions prove a loader/host command-read
acquisition failure. They are not evidence that the restored NOR acquired two
million physical byte changes.

These are two different findings: external SPI corroborated the earlier
two-byte corruption, while the later full USB capture was itself invalid. The
second finding does not retroactively weaken the first.

## Tooling correction and current gate

The historical `kb7-isp-verify.py` source printed an unsupported diagnosis on
CRC failure and returned process status 0. It is retained because historical
plans bind its source identity, but it is no longer pass/fail authority for a
complete USB capture or for distinguishing physical NOR state from read-path
failure. That distinction requires independent evidence such as external SPI.

`tools/flash-access/kb7-isp-repeat.py` is now a fixed, baseline-aware,
dry-run-default read-only gate. It accepts no caller-selected address and can
represent only `F6 00`, `F6 F1`, `F6 17` and `F6 05`. It reads five pinned
4-KiB ranges using 512-, 1,024-, 2,048- and 4,096-byte commands, twenty times
per range/chunk pair. The pass count is not caller-selectable. The reviewed
plan SHA-256 is
`b1f80b218d832d323873ae2225847caf01c280694aa5df10c90c041a3dbe6f94`;
the normalized tool descriptor SHA-256 is
`c38b3ee1435734b483ec4fed3fe3315d31d427e2e6c4fa751b90806f75101a9c`.
Every completed result must be byte-exact against the pinned baseline; a stable
wrong result fails. Transport anomalies emit no clear-halt traffic or explicit
interface close/rebind in that session, while a clean completion requires a
strictly checked release and kernel-driver ownership handoff.

The fixed read-reliability gate has since run on hardware twice; see the
[resolution](#resolution-2026-09-02) below. In this preflight-only revision
`LIVE_READ_ONLY_PREFLIGHT_ENABLED` is true for the exact reviewed campaign and
`LIVE_PROOF_CAMPAIGN_ENABLED` remains false.
The loader-reentry executor refuses mutation in its CLI, in every live entry
point and inside both USB backends before any journal state is published or
any device is opened; the general paired-firmware executor remains locked, and
`flash_approved=false`.

A gate pass does not authorize proof mutation. It permits review of a new
revision that enables only the fixed campaign's full read-only preflight while
leaving mutation false. That full preflight must then establish two exact
32-MiB baseline reads and strict close before a separate review may consider a
new mutation-enabled pin.

## Resolution (2026-09-02)

The fixed gate ran twice on the development unit in separate powered sessions
with the external programmer physically detached both times. With the ~300 mm
SPI leads soldered to the NOR still attached as open stubs it failed 14 of 400
reads (exit 1); after the stubs were cut to ~20 mm and insulated it passed
400 of 400 (exit 0) and the keyboard returned to normal `10f5:5038` operation.
Offline tracing of the V1.22 loader's `F6 05` handler shows the requested
address reaches the flash controller untouched, so the dominant wrong-read
signature, a whole command served from exactly half its address, is a lost
clock in the SPI address phase at the SoC-NOR interface. The `e71b…` capture
above has the same failure family at a higher rate. Full record:
[USB-ISP-READ-RELIABILITY-VALIDATION-2026-09-02.md](USB-ISP-READ-RELIABILITY-VALIDATION-2026-09-02.md).
The gate pass changes no authorization; the next step remains a separately
reviewed preflight-only revision.

## Evidence boundary

The public record contains hashes, offsets, aggregate page classifications and
independently authored validation logic. It does not include either owner
32-MiB capture, an owner journal, flashrom output, USB transcript, proprietary
firmware, or owner-local paths. No result here proves that a checksum-valid
custom Core 0 boots or returns to the preserved loader.
