# Region-1 campaign run record, 2026-09-06

Revision: branch `region1-reentry-mutation-enabled` at `360af17`, executor
source `ba487415…`, campaign `9a582f1c…`, baseline `2b1472f4…`. Bare board on
USB only, SPI pigtails insulated, automount masked and stopped, every
`--commit` run as a transient root service under `/usr/bin/python3`.

## What happened

1. Fresh read-only preflight: exit 0, journal `boundary_verified` 0 at USB
   address 7, live region `04b21e78…`, observed full image `35968ec5…`,
   executor source and implementation hashes as pinned.
2. Twenty install steps, one executor process each with an inspect between:
   all twenty exited 0 in about sixteen minutes. Operation 0, the first
   `F6 06` program onto an already-programmed block this unit has received,
   behaved as a plain page program: the post-read matched boundary 1
   exactly. The journal ended at `proof_installed`, boundary 20, with the
   last two reads equal to the proof image `f5ff8321…` and the live region
   unchanged.
3. First power-cycle: the hub `10f5:503d` re-enumerated; the SoC enumerated
   nothing on its port, neither `5037` nor `5038`, within ten minutes.
4. Second power-cycle (a deliberate, recorded deviation from the runbook's
   one-minute stop, chosen because it sends no USB command): the same
   result within fifteen minutes. The failure is deterministic.
5. No mode switch and no further USB command were sent. The campaign is
   terminal at `proof_installed`; the unit awaits recovery.

## What the evidence says

- The loader accepted the image: a rejected checksum sends the loader to
  its own ISP mode, which enumerates as `5037`. Region 0 was launched.
- Every read before the boot showed the header, loader, manifest and
  region 0 byte-exact, so the recovery routes are intact. The SPI restore
  applies; SWD, if the pads are reachable, would additionally show where
  the core stopped.

## Leading cause: the clock at the reset

The proof re-enters the loader from the state region 0 hands over. Decoding
what the stock main does immediately before its own re-entry shows one
hardware change the proof did not make:

- Region 0's boot selects **198 MHz** (`0x6ebc` calls the clock-source
  switch `0x70b0` with the literal at `0x6f68`, 198000000).
- The stock main, just before relocating (`0x1004a764`), calls region 0's
  clock service `0x6264` (import thunk 68) with **162000000**. That service
  range-checks the frequency, stores it as the requested clock
  (`0x18016568`), enables IRQ 63 and triggers it through NVIC `STIR`; the
  IRQ-63 handler (`0x6028`, vector index 79) switches the clock through
  `0x70b0`, records the actual frequency (`0x1801656c`), re-tunes the DRAM
  controller (`0x7560`) for the new rate and sets the peripheral clock
  global (`0x18016570`) to half; `0x72e8` then confirms requested equals
  actual. The stock main proceeds to the relocation only if that returns 0.
- The only other pre-relocation change is clearing bit 4 of the LCD
  controller (`0x1004ba20`), irrelevant to a system that never enabled it.

So the loader has been observed to start from the ROM's clock at cold boot
and from 162 MHz after the stock re-entry, but never from 198 MHz, which is
where the proof left it. A loader that keeps an already-running PLL and
derives its USB and flash timing from an assumed rate would fail exactly
this way: silently, deterministically, with nothing on the bus.

This is a hypothesis, not a proof. SWD access to the parked core would
settle it; without SWD, the next revision of the proof should mirror the
stock sequence and let the hardware answer.

## What the next proof must do

Before its takeover, and with region 0's vector table still in force so
that the IRQ-63 handler in region 0 can run: call `0x6265(162000000)`,
require 0, wait as stock does, and only then mask, clear, take VTOR and
re-enter the loader. That is a use of a region-0 service, so its closure
(`0x6264`, `0x6028`, `0x70b0`, `0x614c`, `0x7560`, `0x72e8`) must be pinned
and shown to stay inside region 0, and the proof image, campaign identity
and every pin change with it. The unit must be restored to stock first.

## Addendum: what the loader itself does with the clock

The loader's own boot path (closure from its reset vector `0x2c8`, 238
ranges) never programs the PLL or the clock select. Its clock routine at
`0x45a4` sets two enable bits in `SYS0+0`, waits for the ready bits in
`SYS0+8`, runs a register script whose table at `0xb158` is empty, writes
`0xffff` to `SYS1+0xc` (all clock gates and resets on) and then derives the
flash-controller divider from a hard-coded 162 MHz (`0x45ea`: the smallest
shift that brings 162 MHz under 40 MHz, written into `0x40022000` bits
15:12). Region 0's switch to 198 MHz writes `SYS0+0xc` three times
(`0x718c`, `0x71be`, `0x72ae`); the loader never writes that register. So
the loader assumes the clock it inherits is 162 MHz, which holds after the
mask ROM's cold boot and after the stock re-entry, and did not hold after
the proof's reset. The loader's USB timing is derived from the same
assumption, which is the most likely mechanism of the silent failure.

Also checked and not a gap: the loader re-enables the USB PHY
(`0x45000110`) and all `SYS1` gates itself, and read-modify-writes the pin
routing register `SYS0+0x20` that region 0 zeroes at boot.
