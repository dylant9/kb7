# Region-1 loader-reentry proof campaign

Design date: 2026-09-05
Status: offline design, built and simulated against the exact V1.22 baseline;
**not reviewed, not authorized for hardware, and no executor revision consumes
it yet.**

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
`0x0006b000..0x0006c000`), inside the 724-byte window the stock main occupied.
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
| campaign ID | `56aa08c7…` |
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

Because there is no second region whose checksum can serve as an
independent, exactly-known barrier (region 0 is never touched and is always
valid), the simulator does not argue by "opposite-core invalid". Instead it
enumerates every distinct byte-prefix outcome of every operation, 32,470
states across 34,856 modeled cuts, and evaluates the region-1 checksum of
each: none is loader-valid except the exact pre-image at the two stable
endpoints and the exact post-image of the two gate operations. Region 0 keeps
its checksum at every boundary, and the immutable ranges hash-match after
every operation.

Proof boundary: command boundaries, exact payloads and modeled byte-prefix
states. Misaddressing, disturb, torn erases outside the model and
loader-model errors remain external-SPI recovery cases.

## What is still missing before hardware

- **Executor.** The fixed loader-reentry executor is bound to the Core-0
  campaign module and identity. A revision must load this campaign format,
  pin its identity, describe the two mutable sectors in its policy
  descriptor, keep the same journal, barrier, live-region and gate rules,
  and keep both live gates false on the validation branch. The proof-boot
  expectation is identical: the loader self-enumerates `10f5:5037` at a new
  USB address, then the restore direction returns exact stock.
- **Independent review** of the proof image, the builder, the simulation
  argument above and the executor revision.
- **Hardware facts and checker** entries for the region-1 proof identity
  and the campaign, mirroring the Core-0 records.
- The read-reliability and live-region preflight results carry over
  unchanged; a new preflight is still required because journals bind the
  executor source hash.
