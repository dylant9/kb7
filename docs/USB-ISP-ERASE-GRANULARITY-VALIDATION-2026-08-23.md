# USB-ISP guarded erase-footprint validation

Date: 2026-08-23

## Outcome

The fixed four-stage experiment in
[`kb7-isp-erase-granularity.py`](../tools/flash-access/kb7-isp-erase-granularity.py)
completed successfully on one owner-controlled KB7 using the preserved V1.22
loader and the normal-NOR command path.

Every byte of flash sector `[0x000c6000,0x000c7000)` was first programmed to a
known non-`0xff` value. Separate 512-byte non-`0xff` guards were programmed
immediately below and above that sector. After `F6 18`, the loader accepted
`F6 15` block index `0x0630`; all 4,096 target bytes read back as `0xff`, both
guards survived byte-for-byte, and the complete 32-MiB postimage matched the
predicted image exactly.

The two cleanup stages restored the complete main array to its original
baseline. A separately invoked final USB capture matched that baseline, the
saved experiment state was cleared, and the owner subsequently confirmed a
cold boot and normal keyboard operation.

This establishes an **observable exact 4-KiB programmed-data erase footprint**
at the tested target on this unit, with this loader and flash configuration. It
does not turn the experimental command interface into a supported updater.

## Identity and baseline

The run was bound to:

- complete flash size: 33,554,432 bytes;
- preserved-loader window `[0x00001000,0x00010000)` SHA-256:
  `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
- fixed experiment plan SHA-256:
  `a68642a348b18ee27a2f1cfdb6c8137aeff43c0ce14487f9c765c4c76e9be783`;
- two separately invoked, byte-identical full-chip USB captures; and
- baseline SHA-256:
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.

Both baseline captures had the expected header and manifest, and all three
declared region checksums passed as read through the SoC flash controller. The
entire aligned containment envelope `[0x000c0000,0x00100000)` was `0xff` before
the experiment. External SPI recovery had already been rehearsed and remained
available throughout.

## Preparation

The preparation stage made both under-erase and boundary over-erase observable:

- one 512-byte lower guard at `[0x000c5e00,0x000c6000)`;
- eight 512-byte blocks covering every byte of
  `[0x000c6000,0x000c7000)`; and
- one 512-byte upper guard at `[0x000c7000,0x000c7200)`.

Each of the ten blocks used a distinct deterministic pattern with no `0xff`
bytes. Each was programmed with a separate one-block `F6 06` operation after
`F6 18`, polled to completion, and followed by an exact complete-array
comparison. The fully prepared image had SHA-256:

```text
fdda369b75acc245efe119a165df7825649178af30c42096fcd4d2341547a3b7
```

## Target erase result

In a new USB/Bulk-Only-Transport session, the target stage first required an
exact match to the prepared image and revalidated the loader, manifest and
state binding. It then issued:

```text
F6 18
F6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00
```

`0x0630` is `0x000c6000 >> 9`. After the loader reported ready, a complete
32-MiB read matched the exact target-erased image:

```text
0551c79084a3afd0eb7e21ec84b7c01ef74e0f35cc9da2a7b74f45c8cca74c03
```

The observed byte-level result was exactly:

- all 4,096 deliberately programmed target bytes became `0xff`;
- the immediately adjacent lower and upper guards remained exact; and
- no other byte in the 32-MiB loader-visible image differed from the predicted
  postimage.

## Cleanup and functional closure

The lower cleanup stage issued `F6 18` followed by:

```text
F6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00
```

Its exact postimage SHA-256, with only the upper guard remaining, was:

```text
b7959a78477eaa09c40a91692579a7735c812b1b078ccfacc94b21571fda52cb
```

The upper cleanup stage issued `F6 18` followed by:

```text
F6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00
```

The resulting complete image matched the original baseline byte-for-byte. A
separately invoked final 32-MiB USB capture also had SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
The state file was removed only after this exact comparison. The owner then
power-cycled the device and reported normal keyboard operation.

## Evidence boundary

The completed run proves the externally observable programmed-data boundary
for `F6 18` plus normal-NOR `F6 15` at `0x000c6000` on this device and loader.
The immediate non-`0xff` guards make both a sub-sector result and a contiguous
erase crossing either 4-KiB boundary observable. Complete-array comparisons
also detect any other changed byte.

It does **not** prove:

- that every address, device, loader revision or flash revision behaves the
  same way;
- above-16-MiB mutation behavior, `F6 17` mutation mode, or the alternate
  flash-type `F6 19` command;
- the internal NOR opcode or whether erase pulses reached cells that were
  already `0xff` outside the programmed guards;
- atomicity, interruption or power-loss recovery, endurance, or safe retry;
- arbitrary image parsing, multi-sector update planning, or production-updater
  safety; or
- any replacement-firmware clock, memory, USB, display, touch, RGB, Hall or
  pinmux behavior. No replacement firmware was installed or executed.

All byte-level verification used the preserved loader's `F6 05`/SoC flash-read
path. The separately invoked final capture is useful session-level
corroboration, but it is not an electrically independent SPI read. The later
successful cold boot is independent functional evidence, not a bit-level
measurement.

## Consequence

Repeating this destructive footprint experiment merely to reconfirm the same
target is unnecessary. The next software milestone is a version-locked,
offline-first updater planner and interruption simulator. It must constrain all
mutations to reviewed sector images, preserve the loader and immutable stock
data, prevent mixed core-region boots, reconcile interrupted operations from a
fresh full-chip read, and fail closed on any unclassified state. External SPI
remains the demonstrated recovery and ordinary-write path while that work is
developed and physically validated.
