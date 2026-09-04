# Stock Core 0 to region-1 boot contract

Analysis date: 2026-09-05
Inputs: the owner-local byte-exact V1.22 flash capture (full-chip SHA-256
`2b1472f4…`), sliced into region 0 (`core0`, 0xf35c bytes, SHA-256
`d779faf9…`), region 1 (`core1`, 438632 bytes, SHA-256 `b2869bc6…`) and the
loader (61440 bytes, SHA-256 `9cc33333…`).
Verifier: `tools/verify_region1_contract.py` re-derives every fact below from
those images and passed on 2026-09-05. Raw stock bytes stay outside this
repository.

## Why this document exists

The project is changing course: instead of replacing stock region 0 ("Core
0") and region 1 ("Core 1") together, the first custom images keep stock
region 0 untouched and replace only region 1. Region-1 writes can never reach
the header, loader or manifest, and the whole stock boot path up to the call
into region 1 stays exactly as shipped.

That is only sound if the boundary between the two regions is known exactly.
This document is that boundary: what stock region 0 does before it calls
region 1, what state it leaves behind, what it expects region 1 to contain,
and which parts of region 0 a custom region 1 may or may not use.

## One processor, two regions

The SNC7320 in the KB7 runs one Cortex-M core on this path. "Core 0" and
"Core 1" are the vendor's names for the two SN_FWIN manifest regions:

| Region | Flash | Runtime address | Loaded how |
|---|---|---|---|
| 0, `core0` | `0x00011000`, 0xf35c bytes | PRAM `0x00000000` | copied into PRAM by the loader |
| 1, `core1` | `0x00021000`, 0x6b168 bytes | I-cache aperture `0x10000000` | copied by region 0 into OPI DRAM `0x30722000`, mapped through the cache controller |

Region 0 owns the only vector table. Region 1 begins with an import table and
has no vector table of its own. There is no second-core release anywhere on
the boot path.

## The stock boot path, in order

All offsets are region-0 file offsets, which equal PRAM addresses.

1. **Loader.** The loader validates every manifest region checksum, copies
   region 0 into PRAM and resets into it. Its application-launch path
   materializes no region-1 address; the only region-1 dependency is the
   manifest checksum over the 0x6b168-byte image.
2. **Reset handler `0x2f4`.** Reads VTOR, loads SP from the vector table's
   first word (`0x1803f5c0`), calls hardware initialization at `0x6190`
   through a literal, then jumps to the scatter loader at `0x140`.
3. **Hardware initialization `0x6190`**, seven calls in this order:
   1. `0x7008`: clear mailbox words `0x20000000..0x2000000c`.
   2. `0x6ebc`: clock and PLL bring-up on the `0x45000000` system-control
      block; a failure reports code 1 or 3.
   3. `0x7024`: the mask-ROM clock service at `0x0800603d`; failure code 6.
   4. `0x6f70`: OPI DRAM training through `0x40040060`; failure code 5.
   5. `0x6f80`: **region-1 copy and aperture.** SFC control `0x40022000` is
      switched to its copy mode, `memcpy(0x30722000, 0x60021000, 0xde000)`
      copies the whole flash span from region-1 start to `0x000ff000` into
      the top of DRAM, the cache clock bit 11 in `0x4500010c` is set, the
      cache controller at `0x4002f000` gets offset `0x30722000` and control
      value 2, and the first aperture word `[0x10000000]` is compared with the
      first flash word `[0x60021000]`; failure code 4.
   6. `0x7018`: write 0 to `0x45000020`.
   7. `0x6e68`: NVIC and system-handler priorities from a table, then
      `MSR PRIMASK, r0` with `r0 == 0`. **Interrupts are globally enabled
      from here on.** No NVIC set-enable register and no SysTick register is
      touched anywhere on the path.
   Before these calls the handler feeds and disables both watchdogs at
   `0x40008000`/`0x40009000`.
   A failure code other than 6 is recorded through `0x9a74`, which stores the
   code at `0x18023808`, copies 0x34 bytes from mailbox `0x20000f00` and
   calls the persistent-record routine `0x8a8c` (the caller of mask-ROM
   `0x08001491`); every failure then parks in an endless loop. This path is
   not reachable from region 1.
4. **Scatter loader `0x140`.** Walks the table at `0xd75c..0xd79c`:

   | Source | Destination | Length | Handler |
   |---|---|---|---|
   | `0xd8c8` | SRAM `0x18014000` | `0x3804` | decompress (`0x17c`) |
   | `0xe210` | DRAM `0x30100000` | `0x114c` | copy (`0x1e0`) |
   | – | SRAM `0x18017804` | `0x27dbc` | zero (`0x1fc`) |
   | – | DRAM `0x3010114c` | `0x5dea64` | zero (`0x1fc`) |

   So SRAM `0x18014000..0x1803f5c0` and DRAM `0x30100000..0x306ebbb0` are
   fully initialized before any application code runs. The DRAM overlay at
   `0x30100000` is region-0 code executed from DRAM; three region-1 imports
   (`0x30100029`, `0x30100655`, `0x301006f5`) and one region-0 veneer point
   into it.
5. **C runtime entry `0x2d4`.** `0x17a2` sets up the stack from the
   descriptor at `0x32c` (heap `0x180249b0..0x1802a9b0`, stack
   `0x1803d5c0..0x1803f5c0`, SP = `0x1803f5c0`); `0x2a8` initializes the C
   library (heap, stdio handles); then **`bl 0x2196`**, the only call into
   region 1. The veneer at `0x2196` is `MOVW/MOVT ip, #0x1004a525; BX ip`.
   It has exactly one caller. If region 1 ever returned, execution would fall
   through `0x1968`/`0x731c` back into the reset handler.

## State at the region-1 entry

| Item | Value at `0x1004a525` |
|---|---|
| Mode | Thread, privileged, Thumb, MSP |
| SP | `0x1803f5c0` (nothing pushed by `0x2d4`); usable window `0x1803d5c0..0x1803f5c0` |
| LR | `0x2e3` |
| VTOR | whatever the loader left; the vector table at PRAM 0 is region 0's |
| PRIMASK | 0 (enabled) |
| NVIC enables | not written by region 0; inherited from the loader |
| SysTick | not configured |
| Watchdogs | fed and disabled |
| Clocks, PLL, DRAM | configured and trained |
| Region-1 image | copied to DRAM `0x30722000..0x30800000` and served through `0x10000000..0x100de000`; executes from DRAM, not flash |
| SRAM `0x18014000..0x18017804` | region-0 initialized data (decompressed) |
| SRAM `0x18017804..0x1803f5c0` | zeroed, then touched by the C runtime (`0x18024950..0x18024990`, heap, stack) |
| SRAM below `0x18014000` | untouched by region 0; loader helper and globals live at `0x18010000..` |
| Mailbox `0x20000000..0x0c` | cleared |
| Mailbox `0x20000ffc` | loader flag word, untouched by region 0 |
| DRAM `0x30100000..0x3010114c` | region-0 overlay code |
| DRAM `0x3010114c..0x306ebbb0` | zeroed |
| USB | untouched; no USB or PHY register is on the path |

## What region 0 expects from region 1

Only one thing on the boot path: **Thumb code at `0x1004a524`**, plus the
manifest checksum that the loader checks. The reset-path closure (45 code
ranges, 4836 bytes, hash-pinned in the verifier) loads no region-1 address
and materializes none. Region 0 reads region 1 only as an opaque copy.

Everything else region 0 knows about region 1 matters only if that region-0
code runs after the entry:

- **Five vectors** dispatch into region 1: SysTick `0x10012f89`, IRQ4
  `0x10008add`, IRQ5 `0x10008ac5`, IRQ15 `0x1000bd49`, IRQ26 `0x10000db1`.
  They fire only if something enables those sources; region 0 does not.
- **36 veneers** in region 0 (`0x2196..0x22cc` and, in the DRAM overlay,
  `0xe210..0xe22e`) call fixed region-1 addresses. Apart from the entry they
  serve the USB/HID class layer (`0x10057e1d..0x100582ed`), the report
  assembler `0x1000b735`, backlight `0x10012a75` and similar. They are
  reached from region-0 services and the USB IRQ handler `0x62c9`.
- **Region-0 pointer literals** into region 1 (`0x10058970`, `0x10058a87`,
  `0x10058b80`, `0x10058ba4`, `0x10058cf8`, `0x10058e4c`, `0x100590a0`,
  `0x100590f5`, `0x10059284`, `0x100592b8`, `0x100592ec`, `0x10059424`,
  `0x1005973c`, `0x10000800`, `0x10096d5b`) are USB descriptor and class
  tables used by the region-0 USB stack (`0x28a8..0x3296`, `0x468c..0x5498`,
  `0xa11c..0xc010`, `0xe7ea`, `0xf15e`).

## What region 1 may take from region 0

Region 1 imports region-0 services through a table of 79 ten-byte thunks
(`MOVW/MOVT ip; BX ip`) at `0x10000000..0x10000316`. The V1.22 targets are
pinned in the verifier. The stock main uses, in bring-up order, thunk 62
(`0x608d`, eight NVIC priority assignments), 63 (`0xb3e9`), 64 (`0x372d`),
65/66 (`0x44ad`/`0x4885`) or 9/10 (`0x2899`/`0x5f09`) for USB setup, 67
(`0xb79d`, USB state), 56 (`0x26f1`) and 68 (`0x6265`). The proven IN
primitive `0xbcfd` is thunk 8. The earlier USB driver notes describe the
controller bring-up at `0xae60`/`0xb50c`, the endpoint primitive `0x9b70`
and the IRQ dispatcher `0x62c8`.

Using any of these means the corresponding region-0 callbacks into region 1
must exist at their fixed addresses. That mapping is not done and is not
needed for the first campaign.

## Consequences for a custom region 1

1. **Entry.** Provide Thumb code at `0x1004a524`. Everything else in the
   image is free, but the image must keep the exact stock length and be
   CRC-balanced to the unchanged manifest checksum (`0xc8ed2815`) so that
   the manifest stays byte-identical.
2. **Never return.** Park or reset instead.
3. **Own the exceptions first.** Before enabling anything: `CPSID i`, clear
   all NVIC enables and pendings, stop SysTick, then point VTOR at a vector
   table the custom image owns (an SRAM copy). Until VTOR moves, any exception
   goes to region 0's table, five entries of which are stale region-1
   addresses. The loader-reentry proof profile already does the first part
   (review F1, 2026-09-02).
4. **Memory.** After the takeover no region-0 code runs again unless called,
   so all SRAM above the loader's area and all DRAM may be reused. The
   region-1 image itself lives in DRAM and is writable; keep `.data`/`.bss`
   in SRAM as the existing linker script does, because the aperture is an
   instruction cache.
5. **Loader re-entry.** The stock sequence (mailbox marker `0x73207320` at
   `0x20000ffc`, copy `0x60001000..0x60011000` into PRAM from SRAM-resident
   code, AIRCR `SYSRESETREQ`) works unchanged from region 1: the copy
   overwrites region 0 in PRAM, not the running region-1 code in DRAM. The
   replacement firmware's `recovery_trampoline.S` relocates itself below MSP
   and requires MSP inside `0x1803e000..0x1803f5c0`, which the entry state
   satisfies.
6. **Region-0 services.** Not used by the first campaign. A later custom
   region 1 that wants the stock USB stack must first map the callbacks in
   the previous section.

## Proof boundary

Static identity and instruction semantics of the stock reset path only. The
reachable-code ranges were derived with a disassembler and are pinned by
hash; the six indirect branches inside them (`0x172` scatter dispatch,
`0x615e`/`0xb4da`/`0xd416` table switches, `0x707a` the ROM clock call,
`0xd414`) were resolved by hand. Nothing here proves that custom region-1
code executes on hardware; that is what the first region-1 campaign is for.
