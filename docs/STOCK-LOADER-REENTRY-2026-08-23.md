# Preserved-loader re-entry and immutable-loader proof

Review date: 2026-08-23

## Result

The stock firmware contains a complete software path back to the preserved USB
loader. It does not rely on rewriting the loader, a watchdog reset, or the
external `MCU_RST` signal.

The recovered sequence is:

1. write `0x73207320` to retained mailbox word `0x20000ffc`;
2. disable interrupts;
3. copy exactly `0x10000` bytes from XIP address `0x60001000` to PRAM address
   `0x00000000` while executing a small routine from SRAM;
4. request an AIRCR software reset with
   `(AIRCR & 0x00000700) | 0x05fa0004`;
5. restart from the copied loader's PRAM vectors; and
6. have the loader consume, clear and read back the mailbox word before routing
   to its USB updater entry.

A bare AIRCR reset is not enough: the SNC7320 data sheet says software reset
restarts from PRAM. The loader must be copied into PRAM first. This reconciles
the data sheet with the behavior recovered from stock V1.22, V1.24 and V1.33.

The 88-byte stock relocation routine is byte-identical in all three releases,
with SHA-256
`570dc848c53aad3d18ae090580c2dd0687f7273c22693b4860e18dbf99a46315`.
The V1.22 and V1.24 loader inputs are also identical, with SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
V1.33 uses loader SHA-256
`453753e431609116e303a12548ec21c2efd500af4569034bd7947eb5bf43b298`.

The read-only verifier in `tools/verify_loader_reentry.py` binds the complete
owner-local loader and Core-1 inputs to their reviewed sizes and hashes, then
checks the request, relocation, reset and loader-consumer instruction
semantics. It opens no device and writes no file. Raw stock binaries and
disassembly remain outside this repository.

## Replacement-firmware proof profile

The replacement firmware now has an independently authored equivalent in
`drivers/recovery_trampoline.S`. It is gated by
`KB7_ENABLE_UNVERIFIED_LOADER_REENTRY`, which defaults to zero.

`make -C replacement_fw recovery-proof` builds a deliberately minimal Core-0
image that invokes the path immediately after data/BSS initialization and the
stock-equivalent watchdog feed/disable sequence. It does so before
`core0_main()`, clock changes, DRAM, Core-1 execution, USB-device setup, or any
flash mutation. Link-time garbage collection leaves no reachable
`core0_main`, USB-init, flash-erase or flash-program symbol in this profile.

An 84-byte stackless relocation bridge samples MSP only after the C caller's
frame exists, checks the exact stack window and reserve, copies without changing
SP, and branches directly into the relocated code. Its SHA-256 is
`a8c82aa423cc089a563fed7bf2f319f39b2945addf065b47849c04c4d7c793eb`.
The bridge computes linker-symbol distance from checked integer addresses, not
undefined subtraction between distinct C array objects.

The custom SRAM loader-copy routine is 72 bytes and has SHA-256
`43bde11ee9089c930b8e67c6b7d569aec736d719f59f24c6b207d80309a2f539`.
The build proves that:

- the relocation bridge is stackless, relocation-free and does not call C;
- its byte-range symbol is even while its callable Thumb symbol is odd;
- all PC-relative literals are inside the copied blob;
- its executable section has no relocation;
- its live-stack reserve leaves at least 64 bytes beyond the blob;
- the current MSP is inside a narrow, expected Core-0 stack window;
- the mailbox write reads back exactly before PRAM is replaced;
- the copy source, destination and length are exactly those recovered from
  stock; and
- no ordinary firmware bundle or hardware operation is produced.

The separate fixed proof-campaign builder can CRC-balance this ELF into a
checksum-valid V1.22 Core 0 while retaining the exact stock Core 1 and unchanged
stock manifest. Its simulator reports the header, loader and manifest as three
distinct preserved regions and requires zero operations to overlap any of
them. A temporary one-sector Core-1 checksum poison supplies an independent
barrier while Core 0 is rebuilt; that sector is restored to exact stock before
the sparse Core-0 checksum gate is committed.

## What the offline result proves

The following statements are now supported without additional electrical
measurement:

- The stock loader is not part of either application mutation envelope.
- The canonical planner produces no command targeting the header
  `[0x00000000,0x00001000)`, loader `[0x00001000,0x00010000)`, or manifest
  `[0x00010000,0x00011000)`.
- The stock software provides a deliberate valid-application path back to its
  preserved loader.
- The loader itself has a separate application-validation fallback to updater
  entry when both application selections fail.
- The replacement proof profile reproduces the deliberate path before any
  risky application subsystem and contains no flash-writing path.
- Watchdog or external-reset retention of the mailbox is not needed for the
  primary design.

## What still requires one bounded hardware run

Static analysis cannot prove that the custom SRAM routine executes correctly
on this physical unit or that the USB loader enumerates after its reset. The
smallest useful hardware validation is therefore a checksum-valid proof Core 0
with exact stock Core 1, not an intentionally corrupt loader or manifest:

1. retain the demonstrated external-SPI full-image recovery setup and exact
   baseline;
2. build and independently simulate the fixed `recovery-proof` install and
   exact-stock restore campaigns;
3. require the resulting plan to show zero header/loader/manifest operations;
4. install the proof Core-0 envelope using the temporary one-sector Core-1
   checksum barrier, keeping the loader and manifest byte-identical;
5. cold boot and require `10f5:5037` without first invalidating an application
   checksum;
6. read the full flash through the loader and prove the loader, header and
   manifest hashes are unchanged, the proof Core 0 has its declared checksum,
   and Core 1 is byte-exact stock with its declared checksum;
7. restore the exact stock Core 0 through the same fixed campaign; and
8. require an exact full-chip baseline plus normal `10f5:5038` keyboard
   operation.

That run would prove that one checksum-valid custom image can deliberately
return to the untouched stock USB loader. It would not prove recovery from an
arbitrary checksum-valid image whose reset vector never reaches the early
stage, from code that damages clocks or hardware before recovery logic runs, or
from a physically damaged flash. External SPI remains the final recovery route
for those cases.

The [fixed proof campaign and runbook](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md)
implements that offline plan. The exact owner campaign is generated,
independently rederived and pinned. Historical preflights include an exact
boundary-zero pass, but later evidence found an independently SPI-confirmed
two-byte physical corruption followed, after restoration, by a separate
command-aligned USB acquisition failure. Both fixed proof preflight and
mutation are relocked pending the baseline-aware short-read gate, and the proof
itself remains hardware-unrun. The general paired-firmware executor remains
mutation-locked, `flash_approved` remains false, and the scratch executor still
cannot address application or loader regions.
