# KB7 flash access tooling

Two independent paths to the KB7's SPI-NOR (Macronix MX25L25645G, 32 MB), plus
the diagnostics used to characterise them.

This directory is part of the public, source-only repository. It contains no
stock dump, repair image, vendor binary, or extracted firmware. Supply only
images obtained lawfully from hardware you own, keep them outside the
repository, and verify them independently before any write. None of these tools
makes the replacement firmware flash-approved.

| Path | Transport | Reliability | Can write? |
|---|---|---|---|
| **SPI** | ESP32-C3 running `serprog` + `flashrom` | Proven, byte-exact | **Yes — proven** |
| **USB ISP** | Bootloader mass-storage `F6` commands | Reads proven; one marker cycle and one guarded exact-footprint cycle passed on the V1.22 loader | **Narrow lab primitives validated; not a supported flasher** |

---

## ⚠️ Read this first: the unpowered-programmer hazard

**Never leave the ESP32 wired to the flash bus while it is powered off.**

An unpowered CMOS input clamps any signal driven above ~0.7 V through its
ESD protection diode into the dead VCC rail. With the ESP32 attached-but-off,
every SoC flash read fought four parasitic diodes hanging off CS/CLK/MOSI/MISO.

Observed consequences, all of which vanished the moment the ESP32 was unplugged:

* intermittent boot failures (the loader CRC-checks 21 MB of region 2 on every
  boot; one glitched byte drops it to ISP mode)
* a corrupted LCD image (core1, including the display driver, is loaded from
  that same flash)
* an apparent ~0.3 % per-command error rate on USB ISP reads — which
  disappeared completely, 1200/1200 commands clean, once disconnected

Either **power the programmer** or **physically disconnect it**. Wired-and-dead
is the one state to avoid. If you build a permanent harness, put a jumper inline
on the four SPI lines.

---

## Hardware: ESP32-C3 as a serprog programmer

Firmware: [`thisiseth/esp32-serprog`](https://github.com/thisiseth/esp32-serprog)
built with ESP-IDF ≥ 6.0. Upstream's default pins for non-classic targets are
GPIO 40/41/42, which **do not exist on the ESP32-C3** (GPIO0–21 only) — they are
ESP32-S3 pins. Use a C3-specific branch. Strapping pins GPIO2/8/9 are avoided
because an attached flash chip can drive them at reset and force download mode.

| Flash pin | Signal | XIAO pad | GPIO |
|---|---|---|---|
| 1 | CS# | D5 | 7 |
| 2 | DO (MISO) | D2 | 4 |
| 4 | GND | GND | — |
| 5 | DI (MOSI) | D3 | 5 |
| 6 | CLK | D4 | 6 |

Pins 3 (WP#), 7 (HOLD#) and 8 (VCC) are supplied by the board — power the
keyboard for the flash rail and hold the SoC in reset via the RST line so it
stays off the bus. Confirm with `lsusb | grep 10f5`: only `503d` (the hub)
should be present.

**Speed:** 1–4 MHz works reliably over flying leads; 16 MHz fails to probe.
That ceiling is set by the wiring, not the chip — the SoC reads the same part
far faster over PCB traces.

---

## USB device modes

| VID:PID | Meaning |
|---|---|
| `10f5:503d` | CH334F internal hub (always present) |
| `10f5:5038` | Keyboard running normally |
| `10f5:5037` | Bootloader / ISP mode (USB mass storage) |

`kb7-enter-isp.py` switches a running keyboard into ISP mode by sending a vendor
HID feature report to the interface exposing usage page `0xFF90`. Volatile — a
power-cycle restores normal operation.

---

## Verified `F6` command encodings

The bootloader identifies itself as `v0.001 test!` (via `F6 F1`) and its bulk-IN
endpoint fails above 4 KB per transfer, so keep reads at ≤ 0x1000.

### Confirmed on hardware

| Cmd | Function | Encoding |
|---|---|---|
| `F6 00` | Identify | 2 bytes, exactly `01 01` |
| `F6 01` | Read status | 1 byte; bit 0 = WIP |
| `F6 05` | **NOR read** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 06` | **NOR program** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset in the official path); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 17` | Enter 4-byte addressing | no operands |
| `F6 18` | Leave 4-byte addressing for a sub-16-MiB operation | no operands |
| `F6 15` | Normal-NOR erase at the tested target | `CDB[3:5]` = BE16 512-byte-block index; no count |
| `F6 F1` | Device descriptor | 36 bytes |

The V1.22 loader has one confirmed Bulk-Only Transport quirk: for every `F6`
command it leaves CSW `dCSWDataResidue` equal to the requested CBW data length,
even after completing an exact data phase. The tools check this exact value per
command (for example 2 for `F6 00`, 4096 for a 4-KiB `F6 05`, and 0 for a
no-data command). They do not generally permit nonzero or arbitrary residue.

`F6 F1` transfers 36 bytes, but the V1.22 handler explicitly initializes only
bytes 0–27 and 32–35; bytes 28–31 are an uninitialized stack tail included by
its final fixed-size copy. The tools require the exact stable version, device
and magic fields and exclude only that four-byte tail from state hashes. They
still require the complete 36-byte USB transfer.

Static tracing of the vendor orchestration additionally establishes that it
selects `F6 17` when the program or erase range crosses the absolute
`0x61000000` boundary, and `F6 18` (no operands) when the range remains below
it. The 2026-08-23 validation cycle exercised `F6 18` immediately before both
the sub-16-MiB program and erase.

### Erase encoding: static proof plus bounded hardware validation

Calibrated data-flow analysis of the updater proved:

| Cmd | Function | Encoding |
|---|---|---|
| `F6 15` | 4-KiB-path erase | `CDB[3:5]` = BE16 of `(aligned_address >> 9) & 0xffff`; no count |
| `F6 19` | alternate 128-KiB-path erase | `CDB[3:7]` = BE32 of `aligned_address >> 9`; no count |

The erase field is a **512-byte-block index**, unlike read/program. The
shifted value was traced into the builder's address argument and then into the
CDB bytes. A complete companion-SDK review also confirmed that both available
SCSI submission paths copy that 16-byte CDB unchanged and that no lower layer
rescales its fields. See [F6-ERASE-ENCODING.md](F6-ERASE-ENCODING.md) for the
complete proof and [F6-WRITE-ENCODING.md](F6-WRITE-ENCODING.md) for the final
command summary.

`F6 19` is not the automatic “above 16 MiB” form. A separate internal
flash-type selector chooses that path. For both program and erase, the updater
emits `F6 17` when the NOR operation range crosses `0x61000000` and `F6 18`
otherwise. This address-mode choice neither changes the interpretation of the
`F6 15` block index nor reads or modifies the flash-type selector. Normal KB7
NOR erase therefore remains `F6 15` in either address mode. A 16-bit index in
512-byte units covers the entire 32-MiB chip.

On 2026-08-23 the V1.22 preserved loader accepted `F6 15` with block index
`0x0470` after `F6 18` and removed a previously verified marker at flash offset
`0x0008e000`. The complete 32-MiB post-image compared byte-for-byte equal to the
original baseline. That confirms the normal-NOR target interpretation on this
unit; it does not prove exact erase granularity because the rest of the sector
and surrounding gap were already `0xff`. `F6 19` remains untested.

The fixed follow-up `kb7-isp-erase-granularity.py` subsequently populated every
byte of sector `0x000c6000`, placed non-`0xff` guards immediately below and
above it, and required the whole
aligned `[0x000c0000,0x00100000)` containment envelope to be erased in the
baseline. It additionally pins the actual preserved-loader flash window
`[0x00001000,0x00010000)` to SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`
in the offline baseline, every live full-chip preflight and the saved state; USB
identify replies alone are not accepted as proof of the executing loader code.
Its plan hash also binds the literal ten `F6 06` and three `F6 15` CDBs, the
`F6 18` mode subcode, flash/block/sector sizes, payload hashes, geometry, and
SHA-256 of the experiment, strict writer and verifier source files. With the
reviewed source tree that fixed plan hash is
`a68642a348b18ee27a2f1cfdb6c8137aeff43c0ce14487f9c765c4c76e9be783`;
source or command drift changes it and invalidates prior stage state. This is a
fail-closed consistency check, not code signing.
It is dry-run by default and has four identity- and image-bound stages: prepare,
erase the target, clean the lower guard, and clean the upper guard back to the
exact baseline. That fixed cycle passed on the development unit: all 4,096
target bytes erased, both adjacent guards survived exactly, every 32-MiB
postimage matched its prediction, cleanup restored the baseline, and the owner
then confirmed a working cold boot. This proves an observable exact 4-KiB
footprint only at that target with this unit and loader. See the
[runbook](ERASE-GRANULARITY-TEST-PLAN.md) and
[dated result](../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md).

### The disproven Phase-0 program model

An earlier model treated `F6 06` as taking a **scaled** address
(`aligned_offset >> 9`) and a **byte** count. Both assumptions were wrong, as
established destructively:

> Sent `f6 06 00 00 00 04 70 01 00 …` intending "program 256 bytes at
> `0x8e000`" (scaled index `0x470`, byte count `0x0100`).
> The device wrote **128 KB starting at byte address `0x470`**.
> Damage spanned `0x470`–`0x2046f`; last changed byte `0x2046f` = `0x470 +
> 0x20000` exactly.

So `F6 06` takes:
* a **raw byte address** — the same encoding as `F6 05`, *not* a scaled index
* a count in **512-byte blocks** — `0x0100` meant 256 × 512 = 128 KB

This overwrote the header, bootloader, manifest and core0. Recovery required a
full-chip rewrite over SPI.

The re-analysis first reproduced that known result from the updater before applying
the same argument trace to erase. In the program path the `>> 9` is applied to
the transfer **size**; in the erase path it is applied to the aligned
**address**.

### ⚠️ Bounded USB mutations validated — not a supported flashing path

**If you have found this repository and want to flash a KB7: use the SPI path.**
The narrow marker cycle and fixed erase-footprint cycle have passed under
laboratory guards; no general USB updater exists. Treat anything here that
writes over USB as experimental and capable of destroying your bootloader.

Host-side address validation **cannot** protect against device-side
misaddressing. An earlier host tool correctly refused intended targets outside
the scratch window — but the device acted on the *encoded* value (`0x470`), not
the intended offset (`0x8e000`), and overwrote the header, bootloader, manifest
and core0. Recovery required a full-chip SPI rewrite.

`kb7-isp-write2.py` settled the loader-side `F6 15` question for one V1.22 unit,
target and command size. Its exact reviewed sequence passed once. It remains
**dry-run by default**, derives an unused scratch sector from the connected
manifest, requires exact full-chip pre/post images, and refuses to erase unless
a separately verified program stage left its bound marker and authorization
state. It is a restricted validation experiment, not a flashing tool. See
[WRITE-TEST-PLAN.md](WRITE-TEST-PLAN.md) before considering its explicit
`--commit` mode.

The separate `kb7-isp-erase-granularity.py` does not broaden that primitive
into a flasher. Its address, patterns, geometry and commands are fixed solely to
make an under- or over-erase observable at one guarded target. Its completed
hardware pass proved that observable exact 4-KiB footprint for the tested V1.22
loader, unit and target. It did not prove `F6 19`, arbitrary update planning or
power-loss recovery, and the fixed script remains destructive and unsuitable
as an updater.

The successful cycle does not make another mutation intrinsically safe:
transport failure, power loss, an untested offset/version or a future tooling
defect can still damage the boot chain. The loader is an early `v0.001 test!`
build and its USB bulk path has other observed limitations.

**Do not attempt a USB write without a working SPI programmer, a byte-exact
backup of your own device, and a willingness to spend 30 minutes restoring it.**

---

## Tools

### SPI path (flashrom + ESP32)

| Script | Purpose |
|---|---|
| `kb7-read-1m.sh` / `-4m` / `-8m` / `-16m` | Full-chip read at a given SPI clock; requires an output path and optionally checks a caller-supplied SHA-256 |
| `kb7-compare.sh <dumpA> <dumpB>` | Diff two caller-supplied dumps: clusters differences, reports bit-flip direction, and checks all three region CRCs |
| `kb7-repair-layout.txt` | flashrom layout confining a write to `0x00a00000-0x00a0ffff`, keeping the bootloader outside the written region |

Incident-specific surgical restore example (only the named region is touched):

```sh
flashrom -p serprog:dev=/dev/ttyACM0:921600,spispeed=1M \
  -c "MX25L25635F/MX25L25645G" \
  -l kb7-repair-layout.txt -i repair -w <image>.bin --progress
```

`<image>.bin` must be a verified, owner-supplied full-chip image whose bytes for
that exact repair region are known-good; this is not a generic custom-firmware
installation command. Keep the SoC in reset, verify 3.3-V signalling, and retain
two matching backups before writing. Flashrom verifies the **whole chip** by
default after writing; add `-N` to verify only the written region.

### USB ISP path

| Script | Purpose | Safety |
|---|---|---|
| `kb7-enter-isp.py` | Switch a running keyboard into ISP mode | volatile; asks before sending |
| `kb7-isp-verify.py` | Read flash **through the SoC's own controller** and verify region CRCs | **read-only** — mutating opcodes are unrepresentable |
| `kb7-isp-repeat.py` | Re-read one region N times across chunk sizes to measure read repeatability | read-only |
| `kb7-isp-write2.py` | Two-stage marker-program/sector-erase validation experiment | **destructive; dry-run by default; not a firmware flasher** |
| `kb7-isp-erase-granularity.py` | Fixed four-stage guarded test of the observable `F6 15` erase footprint | **destructive; dry-run by default; passed once at the fixed target** |
| `WRITE-TEST-PLAN.md` | Exact experimental sequence, remaining failure modes and SPI recovery procedure | documentation only |
| `ERASE-GRANULARITY-TEST-PLAN.md` | Fixed target, exact four-stage sequence, proof limits and SPI recovery procedure | documentation only |
| `F6-ERASE-ENCODING.md` | Calibrated static proof of the erase address units and CDB layouts | documentation only |
| `F6-WRITE-ENCODING.md` | Final program/erase investigation record and safety verdict | documentation only |

`kb7-isp-verify.py` is the useful one: it exercises the same flash read path the
bootloader uses at boot, so it can distinguish "the chip is bad" from "the SoC's
read of the chip is bad" — a distinction the SPI programmer cannot make.

`kb7-isp-write2.py` is deliberately not a general writer. It accepts only the
reviewed marker-program and sector-erase experiment, opens no USB device in its
default dry run, and requires an explicit `--commit` for either destructive
stage. That sequence passed once on the V1.22 development unit at `0x8e000`;
other offsets, lengths, loader revisions, interruption behavior and `F6 19`
remain outside its evidence. Its guards bound host-side mistakes; they cannot
make an incorrect or faulty loader handler safe. For ordinary or production
writes, continue to use the proven external-SPI procedure. This project remains
`flash_approved=false`.

`kb7-isp-erase-granularity.py` is similarly fixed and fail-closed. It uses
sector `0x000c6000`, programs all eight of its 512-byte blocks, and brackets the
sector with adjacent 512-byte guards. The required erased containment envelope
is `[0x000c0000,0x00100000)`, wholly inside the reviewed V1.22 scratch gap; this
bounds plausible 64/128/256-KiB over-erase while making it detectable. Each
stage checks the reviewed 60-KiB preserved-loader flash hash before mutation.
The state-bound fixed plan covers that hash plus every mutation CDB, geometry
and source-file hash, so changing the implementation between stages fails
closed. Each stage opens a fresh USB session without requiring a physical power
cycle, requires an exact full-chip preimage, persists a started state before
mutation, and accepts only its exact full-chip postimage. Read the dedicated
plan before even running its offline dry mode.

The four-stage run has now passed once at this exact target. All target and
guard postimages matched, the complete baseline was restored, and the keyboard
subsequently cold-booted normally. Do not repeat it merely to reconfirm that
same bounded fact.

---

## SN_FWIN region map (V1.22)

| Region | Store offset | Length | Load VMA | CRC |
|---|---|---|---|---|
| header | `0x0` | `0x1000` | — | none |
| loader | `0x1000` | `0xf000` | `0x0` | none |
| manifest | `0x10000` | `0x1000` | — | — |
| 0 (core0) | `0x11000` | `0xf35c` | `0x00000000` | `0xc3f43a6f` |
| 1 (core1) | `0x21000` | `0x6b168` | `0x10000000` | `0xc8ed2815` |
| 2 (assets) | `0x100000` | `0x146af8c` | `0x60100000` | `0xaa83e9a3` |

Region CRC = `sum(zlib.crc32(chunk)) mod 2**32` over `0x10000`-byte chunks.
**The loader validates every region CRC at boot** and falls back to ISP mode on
any failure — verified empirically: 52 corrupted bytes in region 2 (asset pixel
data, functionally cosmetic) were enough to stop the keyboard booting.

Free space: `0x8c168`–`0x100000` (~464 KiB, all `0xFF`). The post-image tail is
**not** free — user settings, keymaps and RGB profiles live at `0x1a00000` and
are rewritten during normal operation.
