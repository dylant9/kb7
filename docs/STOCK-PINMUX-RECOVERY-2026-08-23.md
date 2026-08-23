# Stock pinmux recovery — 2026-08-23

## Result

The KB7 LCD, MCU2 SPI and backlight pin modes are recoverable offline. They no
longer require a passive stock-powered register capture or an invented generic
`SYS0_PINCTRL` encoding.

The earlier blocker came from a wrong model of the SNC7320 pin table. Its
`Mode 1` through `Mode 7` columns are priority-ordered peripheral functions;
they are not a three-bit selector stored independently for every pad. The
datasheet says that when multiple peripheral functions are enabled, the
lowest-numbered mode has priority. Ordinary default groups are therefore
selected by enabling their controllers. `SYS0_PINCTRL` selects only the
exceptional alternate groups called out by the table footnotes.

This conclusion combines the complete stock static recovery with the SNC7320
datasheet and the peer AT32F423 datasheet. Decompilation was already complete
enough to contain the relevant writes, but a decompiler cannot invent the
datasheet's register semantics or distinguish a generic mux field from a group
selector. Reconciliation of those two evidence sources was the missing step.

## SNC7320 datasheet model

Pages 24–26 of revision 2.1 identify the special alternate groups and flag the
PWM routes as requiring `SYS0_PINCTRL`; the stock writes resolve the KB7 PWM
selector:

| Bit | Special selection |
|---:|---|
| 0 | alternate NAND group |
| 1 | alternate LCD/8080 group on P1 pads |
| 8 | alternate SPI0DMA group |
| 17 | P0.6 `CT32B6_PWM1` route used for the KB7 backlight (resolved from stock) |

The default RGB18 LCD group on P2.4 through P3.9 has no alternate-group
footnote. The SPI0 group on P0.14, P0.15, P1.0 and P1.1 likewise has no
alternate-group footnote. A cleared `SYS0_PINCTRL` therefore selects the groups
used by the KB7 while their respective peripheral controllers are active.

`GPIO_PnCFG` and `GPIO_DIRECTION` are separate GPIO electrical controls. Stock
does not use them as a generic peripheral mux. The replacement driver now
leaves those GPIO registers untouched for accepted alternate-function pads.

## Exact stock evidence

Three independently identified releases reproduce the same policy:

| Stock release | Core0 SHA-256 | Core0 clear | Core1 SHA-256 | PWM route RMW |
|---|---|---:|---|---:|
| V1.22 | `d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153` | `0x00007018` | `b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72` | `0x10008af4` |
| V1.24 | `79eb92bc73ddccbfff682927df7c951802fd64c9863cdeacd9b230642b5ca695` | `0x0000738c` | `dcb06f976dcaff81d0c5ccd1fdfebcb5b6ca4ec3d7e003ad1e90f896a4139aa7` | `0x10008e64` |
| V1.33 | `30f791af363b39f472095152118413421e525a2ed09fef87b236f1a437e32cc6` | `0x00003534` | `d64df057dbdd125b12f156b57de5ad75a9a0d5804e30a16bb9ef1a56830d101f` | `0x1000cc6c` |

Each Core0 image contains the same ten-byte routine that writes zero to
`SYS0 + 0x20`. Each Core1 image later uses the same read-modify-write policy to
set only bit 17 for timer-6 PWM. No LCD- or SPI0-specific `PINCTRL` write is
present.

The recovered V1.22 serial initializer selects instance 0, whose controller is
SPI0 at `0x4000e000`, and accesses only the SPI controller registers. The
recovered LCD initializer programs the PPU/TFT controller at `0x40050000`
without another `PINCTRL` write. These call paths agree with the default groups
in the datasheet.

## AT32F423 peer corroboration

The secondary MCU is an AT32F423. Its stock V1.15 image
(`8452e825bc71bda5696ecc8b33d3b31e1f7a8f0d4ed677985d2532768e92aa66`)
configures:

- PA15 as SPI3 CS, AF6;
- PC10 as SPI3 SCK, AF6;
- PC11 as SPI3 MISO, AF6; and
- PC12 as SPI3 MOSI, AF6.

The recovered GPIO setup is at `0x08006fec` and the matching SPI3 DMA setup is
at `0x08006e24`. These assignments are independently listed in the
[official AT32F423 datasheet revision 2.02](https://www.arterychip.com/download/DS/DS_AT32F423_V2.02_EN.pdf).
They corroborate the peer endpoint of the SNC SPI0 link.

This is not a claim that PCB continuity was measured. It is stronger than a
continuity measurement for the software question: both endpoints' exact pin
modes and peripherals are identified from their own firmware and datasheets.

## Voltage-domain conclusion

There is no recovered software choice between “1.8-V GPIO mode” and “3.3-V
GPIO mode.” SNC GPIO belongs to the `VDDIO33` domain. The 1.82-V rail is for
the external OPI/DRAM interface and the approximately 1.22-V rail is the core
supply. Those rail values still matter when attaching external electronics or
diagnosing power sequencing, but measuring them does not reveal an additional
GPIO mux setting and is not a prerequisite for reproducing stock pin modes.

## What remains physical

Static recovery closes the pin-selection question. Hardware testing is still
useful for dynamic behavior that binaries and datasheets cannot prove on this
particular board: panel image timing, touch coordinates, Hall calibration,
RGB-to-key correlation, sustained USB behavior, and final end-to-end operation.
Those are functional validation gates, not missing pinmux encodings.

The labeled `MCU_RST` pad has already held the SoC away from the serial flash
during repeated exact reads and a successful full restore. Direct continuity
to package lead 88 would add documentation, but is not required to reuse the
demonstrated recovery procedure.

No stock binary, decompiler output, raw capture or proprietary register dump is
included in this public record.
