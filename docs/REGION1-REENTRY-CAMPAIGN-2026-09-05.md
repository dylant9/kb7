# Region-1 loader-reentry proof campaign

Design date: 2026-09-05
Status: offline design, built and simulated against the exact V1.22 baseline
and bound to the fixed executor on this branch with both live gates false;
**not reviewed and not authorized for hardware.**

## Purpose

The first custom code to run on the KB7 should touch as little of the stock
image as possible and leave every recovery path in place. This campaign
keeps the stock header, loader, manifest and region 0 ("Core 0") byte for
byte, patches one region-1 flash sector so that the stock application entry
runs a 404-byte proof instead of the stock main routine, and restores exact
stock afterwards. The proof masks and clears every interrupt, takes VTOR, and
re-enters the preserved USB loader through the stock-equivalent relocation.
Cold boot should therefore self-enumerate as `10f5:5037`.

It replaces the earlier Core-0 proof campaign
([LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md))
as the first hardware step. The Core-0 campaign, its mutation-enabled branch
and its review remain valid and unchanged as a fallback.

## Why region 1, and why one sector

The boot contract
([STOCK-CORE0-REGION1-CONTRACT-2026-09-05.md](STOCK-CORE0-REGION1-CONTRACT-2026-09-05.md))
shows that stock region 0 needs exactly one thing from region 1: Thumb code
at `0x1004a524`. Everything else it knows about region 1 is reached only
through services the proof never calls. So the proof lives at that entry, in
the sector `0x0004a000..0x0004b000` (region-1 offsets; flash
`0x0006b000..0x0006c000`), inside the 724-byte window the stock main
occupied; the builder refuses any proof whose code, fixup and gate words
would extend past that window.
The loader's only region-1 check is the manifest checksum, so the sector is
CRC-balanced to the unchanged checksum `0xc8ed2815` and the manifest stays
byte-identical.

Patching one sector rather than replacing region 1 keeps the campaign small:
40 operations instead of the Core-0 campaign's 168, and about a quarter of
the full-chip reads. Every read is a chance for the residual read fault that
ends a campaign with exit 3, so fewer operations matter.

## Proof image

`make -C replacement_fw region1-reentry-proof` builds
`build/region1-reentry-proof.elf`:

| Item | Value |
|---|---|
| Sources | `core1/region1_reentry_proof.c`, `drivers/recovery.c`, `drivers/recovery_trampoline.S` |
| Linker | `linker/region1-reentry-proof.ld`, `.text` fixed at `0x1004a524` |
| Entry | `0x1004a525`; naked: `CPSID i`, MSP = `0x1803f5c0`, `DSB`, `ISB`, branch |
| Main | NVIC ICER/ICPR all clear, SysTick off, 79-entry park table written to SRAM `0x18030000`, VTOR set through a literal, then `kb7_enter_loader()` |
| Loader entry | unchanged `recovery.c`: marker `0x73207320` at `0x20000ffc` with read-back, SysTick/NVIC off, stackless bridge, 72-byte SRAM routine copies `0x60001000..0x60011000` into PRAM and requests AIRCR reset |
| Raw | 404 bytes, SHA-256 `e753380b…`, no `.data`, no `.bss`, no relocations |
| Pinned in | the Makefile target (size, hash, entry, single `AX` section inside the sector, relocator `a8c82aa4…` and trampoline `43bde11e…` unchanged) and the campaign builder |

Faults after the takeover park in the proof's own table. Faults before it
reach region 0's handlers, exactly as they would for stock.

## Campaign layout

Built by `tools/flash-access/kb7-region1-reentry-campaign.py` from the two
exact baselines and the proof ELF; verified by re-derivation.

| Direction | Operations |
|---|---|
| install | poison (1 program) → erase patch sector, 8 programs with the gate erased → erase poison sector, 8 stock programs → gate program |
| restore | poison (1) → erase patch sector, 8 stock programs with the restore gate erased → erase poison sector, 8 stock programs → gate program |

Totals: 40 operations, 4 erases, 36 programs; two mutable sectors
(`0x0006b000` patch, `0x00022000` poison, the same poison sector the Core-0
campaign uses); zero operations in the header, loader, manifest, region 0 or
anywhere after region 1.

Identities for the exact V1.22 baseline `2b1472f4…`:

| Item | Value |
|---|---|
| campaign ID | `9a582f1c…` |
| proof full-chip image | `f5ff8321…` |
| patched region 1 | `472091e0…`; only sector `0x4a000` differs from stock |
| install fixup / gate | `0x4a6b8` / `0x4a6bc`, both rank 32; gate final word `00000000` |
| restore gate | `0x4a000`, the sector's first word, rank 32 |

## Barriers and what the simulation proves

1. **Poison first.** One erased bit in a separate stock sector is cleared
   before any erase, so region 1 is invalid before the patch sector is
   touched. The poison has exactly two modeled outcomes: exact stock or the
   one-bit-invalid image.
2. **Gate erased during the rebuild.** The patch sector is written with its
   four-byte gate erased; the gate has GF(2) rank 32 within its 64-KiB CRC
   chunk, so only the exact final word reaches the declared checksum.
3. **Poison sector restored under the erased gate.** The poison sector goes
   back to exact stock while the gate is still erased.
4. **Gate last.** The sparse gate program is the only operation that makes
   region 1 valid, and it produces the exact target.

**The independent barrier of the Core-0 campaign is lost here, and that
should be said plainly.** In the Core-0 campaign the other region's checksum
was the barrier: with Core 1 poisoned, no Core-0 content whatsoever could
boot, whatever physical state a Core-0 sector was in. In this campaign the
patch sector and the poison sector are terms of the same region-1 checksum
sum. For a physical state of the patch sector that lies outside the
byte-prefix model (a torn erase or program that is not a prefix), validity
requires the sector's 64-KiB chunk CRC to equal one specific 32-bit value;
the poison only changes which value. The poison therefore still guarantees
that region 1 is invalid before the first erase and that the poison-sector
restore happens under an erased gate, but it adds nothing against unmodeled
states beyond what the enumeration gives.

What remains is exact under the model: the simulator enumerates every
distinct byte-prefix outcome of every operation, 32,470 states across 34,856
modeled cuts, and evaluates the region-1 checksum of each. None is
loader-valid except the exact pre-image at the two stable endpoints and the
exact post-image of the two gate operations. Region 0 keeps its checksum at
every boundary, and the immutable ranges hash-match after every operation.
Outside the model the residual is a 2^-32-class coincidence per distinct
physical state of the patch sector during the nine dense operations of each
direction. Its consequence is bounded: intact stock region 0 would run a
torn region 1, which hangs or faults; the recovery is the external SPI
restore, the same class as every other unmodeled outcome.

A later revision could restore an independent barrier with a single-bit
poison in region 2 (manifest entry 2, whose CRC failure was observed on the
device on 2026-08-22 to send the loader to ISP mode). That needs planner and
executor envelope changes and its own review; it is not part of this
campaign.

Proof boundary: command boundaries, exact payloads and modeled byte-prefix
states. Misaddressing, disturb, torn erases outside the model and
loader-model errors remain external-SPI recovery cases.

One stock hazard is live on the proof boot that the Core-0 proof never
carried: stock region 0's own failure handling. A hardware-init failure
(clock, PLL, the region-1 copy's first-word check, DRAM training) or a
HardFault before the proof takes over records the failure through the
mask-ROM persistent-record service targeting header offsets
`0x800..0xbff`, then parks. On this unit that area has no erased slot, so
the stock code writes nothing after the ROM call, and the ROM's own
behaviour is not decoded. Any header change would fail the executor's
byte-exact comparison below the live region and end the campaign with exit
3 and an SPI restore; it would not by itself change how the unit boots,
because the loader checks manifest regions, not the header. A read fault
during the region-1 copy is exactly what trips the first-word check, so
short SPI lead stubs matter for this boot as much as for the reads.

## Status on this branch

- **Executor.** The fixed loader-reentry executor loads this campaign
  format instead of the Core-0 one, pins campaign `9a582f1c…`, hashes both
  campaign modules, describes the two mutable sectors and the zero region-0
  operations in its policy descriptor, and keeps every journal, barrier,
  live-region and strict-close rule unchanged. On this branch both live
  gates are true for that identity only. The proof-boot expectation: the
  loader self-enumerates `10f5:5037` at a new USB address, then the restore
  direction returns exact stock. The Core-0-bound executor revisions remain
  on their own branches.
- **Reviews.** The offline revision was independently reviewed on
  2026-09-05 (clean with non-blocking notes, closed), and the
  mutation-enabled revision the same evening (clean with non-blocking
  notes, closed in the commit after it).
- **Hardware.** The read-only preflight passed on 2026-09-05
  ([record](REGION1-REENTRY-PREFLIGHT-2026-09-05.md)). The campaign itself
  has not run; the [runbook](REGION1-REENTRY-RUNBOOK-2026-09-05.md) governs
  the session, which starts with a fresh preflight because journals bind
  the executor source hash.
