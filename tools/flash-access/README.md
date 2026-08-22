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
| **USB ISP** | Bootloader mass-storage `F6` commands | Reads proven; program observed; erase encoding static-only | **No — read-only policy** |

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
| `F6 00` | Identify | returns `01 01 …` |
| `F6 01` | Read status | 1 byte; bit 0 = WIP |
| `F6 05` | **NOR read** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 06` | **NOR program** | `CDB[3:7]` = BE32 **raw byte address** (`0x60000000` + offset in the official path); `CDB[7:9]` = BE16 count in **512-byte blocks** |
| `F6 17` | Enter 4-byte addressing | no operands; required above 16 MB |
| `F6 F1` | Device descriptor | 36 bytes |

### Erase encoding: resolved statically, not validated on hardware

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
flash-type selector chooses that path. The updater emits `F6 17` independently
when the NOR address range crosses `0x61000000`, and normal KB7 NOR erase
remains `F6 15`. A 16-bit index in 512-byte units covers the entire 32-MiB chip.

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

### USB writing remains disabled

Host-side address validation **cannot** protect against device-side
misaddressing. The experimental host tool correctly refused intended targets
outside the scratch window—but the device acted on the *encoded* value
(`0x470`), not the intended offset (`0x8e000`). No USB mutation tool or command
emitter is included in the public tree.

Even with the encoding statically resolved, there is no erase test that is
non-destructive under every remaining implementation failure. The loader is an
early `v0.001 test!` build and the USB bulk path has other observed limitations.
Use USB ISP only for diagnostics and reads; use the proven SPI path for all
writes.

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
| `F6-ERASE-ENCODING.md` | Calibrated static proof of the erase address units and CDB layouts | documentation only |
| `F6-WRITE-ENCODING.md` | Final program/erase investigation record and safety verdict | documentation only |

`kb7-isp-verify.py` is the useful one: it exercises the same flash read path the
bootloader uses at boot, so it can distinguish "the chip is bad" from "the SoC's
read of the chip is bad" — a distinction the SPI programmer cannot make.

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
