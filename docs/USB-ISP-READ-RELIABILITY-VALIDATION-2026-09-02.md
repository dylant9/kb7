# USB-ISP read-reliability gate: hardware result

Date: 2026-09-02

## Result

The fixed read-only sweep `tools/flash-access/kb7-isp-repeat.py` (source
`27d85c69e902c3059f046dfb1862c30b572c94b1dd9020d97ec69755bca097a9`, plan
`b1f80b218d832d323873ae2225847caf01c280694aa5df10c90c041a3dbe6f94`, normalized
descriptor `c38b3ee1435734b483ec4fed3fe3315d31d427e2e6c4fa751b90806f75101a9c`,
reference baseline
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`) ran twice
on the V1.22 development unit in separate powered sessions from branch HEAD
`aa5d47be6ca484051a32e5f5623f1c32f355787b`.

| Run | NOR SPI lead stubs | Wrong passes of 400 | Exact observations | Exit |
|---|---|---|---|---|
| 1 | ~300 mm, unterminated, programmer detached | 14 | 386 | 1 |
| 2 | cut to ~20 mm and insulated | 0 | 400 | 0 |

Run 2 satisfied every gate criterion: 20 of 20 range/chunk entries reported
`passes: 20`, `exact_passes: 20`, `distinct_results: 1`, `passed: true`, each
observed digest equalled its baseline-slice digest, the explicit PASS line
printed, the strict close released the interface and the kernel driver
re-bound, and a normal power-cycle restored `10f5:5038` with working keyboard
function confirmed by the owner. The two owner-local logs have SHA-256
`bbd90f37a73bddfaf29035406385a51268cbfa42fac01ccd30944c5031380d9f` (run 1) and
`c8fb524b77be3c8fe2cf3bd7fd2890267db1fc43e35b7dfc19f80057e9c02ce9` (run 2).

## Session conditions

Recorded per note N2 of the 2026-09-02 independent review:

- External ESP32 programmer: physically disconnected in both runs. It was also
  not attached for the 2026-08-31 `e71b…` capture.
- NOR leads: the four SPI signal leads and ground soldered to the flash stayed
  attached as ~300 mm open stubs in run 1, and were cut to ~20 mm and insulated
  before run 2.
- Nothing else changed between runs: same host and running kernel, same tool,
  verifier, plan and reference pins, same back-to-back command cadence, bare
  motherboard, ISP mode entered by the vendor HID mode-switch both times, no
  mass-storage mount, one `10f5:503d` hub and one keyboard on the bus.

## Failure structure of run 1 and of the `e71b…` capture

| Whole-command outcome | `e71b…` 2026-08-31, 8,192 commands | Run 1, 1,500 commands |
|---|---|---|
| data from exactly `offset >> 1` | 184 (23 more ambiguous with erased pages) | 3 |
| all zero | 194 | 7 |
| all `0xff` | 40 | 1 |
| copy of a page 2 to 7 pages away, either direction | 28 | 1 (one block late) |
| other wrong address or partial | 112 | 2 |
| **wrong commands** | **558 (6.8 %)** | **14 (0.9 %)** |

In run 1 the wrong-command rate was flat across 512-, 1024-, 2048- and
4096-byte commands (7/800, 4/400, 2/200, 1/100), so the fault is per command,
not per byte. Every address read exactly at least 17 times out of 20, so no
result was stable-but-wrong. In `e71b…` the 558 wrong pages form 485 isolated
events, 32 pairs and 3 triples spread evenly over the chip, independent of
whether the page or its neighbour is erased. USB bulk data is CRC-protected and
every CBW, CSW, tag and residue check passed, so the wrong bytes were produced
on the device side. Independent external-SPI reads of the same NOR are
byte-exact, so the NOR contents are not the cause.

## Loader read path

Offline disassembly of the preserved V1.22 loader window (flash
`0x1000..0x10000`, SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`) locates the
SCSI opcode classifier at loader offset `0x4d70`, the vendor `F6` subcode
dispatcher at `0xa614` with its subcode table at `0xa66a`, the `F6 05` handler
at `0xa6ee` and the flash-read routine at `0x3660`. The handler byte-swaps the
CDB address and block count, shifts the count by nine, and the read routine
builds a DMA descriptor whose source is the untouched absolute XIP address
`0x60000000 + offset`, destination a RAM buffer and length the exact byte
count, submitted to the controller at `0x40022000`. No code path halves,
offsets or zeroes the address. (The private MMIO map's earlier inference that
`0x40023000` is the NOR read controller does not hold for this path.)

Data returned from exactly `offset >> 1` therefore means the NOR received the
address shifted right by one bit: one clock lost, or one edge missed, in the
SPI command/address phase. A wrong dummy-cycle or mode configuration would
shift the data phase instead, and a 3-byte versus 4-byte address mismatch
would shift by a whole byte and key off the 16 MiB boundary; failures occurred
on both sides of it. The zero, `0xff` and neighbouring-page outcomes are the
same glitch at other severities: an aborted transfer, no data driven, a stale
descriptor.

## Cause

The ~300 mm unterminated lead stubs at the SoC's XIP clock. flashrom drives
the same leads at 1-4 MHz, which never exposed the problem, and 16 MHz was
already known to fail over the flying leads. Removing the stubs removed the
fault: the probability of zero wrong commands in 1,500 at the run-1 rate is
about e^-14. The stub effect is marginal and routing-dependent, which is why
some earlier lead-attached sessions read clean. The unpowered-programmer clamp
documented in `tools/flash-access/README.md` is a separate, additional hazard;
"programmer physically disconnected" was never a sufficient condition.

## What this establishes and what it does not

- Established: the fixed gate passes on this unit with short stubs; the
  2026-08-31 and 2026-09-02 wrong reads were acquisition faults at the SoC-NOR
  interface, not USB and not NOR content.
- Not established: a zero residual rate (0 of 1,500 commands bounds it near
  0.2 % at 95 % confidence); reliability of a full 32 MiB, 8,192-command
  acquisition; the boot-path flash clock, since the boot CRC check of about
  21 MB kept passing at a rate that should have failed it; anything about
  program or erase.
- Authorization: unchanged. `LIVE_READ_ONLY_PREFLIGHT_ENABLED` and
  `LIVE_PROOF_CAMPAIGN_ENABLED` remain false. A gate pass permits only review of
  a separate preflight-only revision; proof mutation needs a later exact full
  preflight and its own review.
