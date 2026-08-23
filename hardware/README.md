# Hardware evidence artifacts

These files are independently authored, machine-readable interoperability
summaries. They do not contain the Sonix PDF, vendor firmware, decompiler
output, PCB captures, or copied vendor tables.

- `snc7320-soc.json` records datasheet-confirmed architecture, memory, MMIO
  block bases, interrupts, DMA windows, clock/electrical limits, and known
  document inconsistencies.
- `kb7-pin-map.json` joins package-lead facts to clean-room KB7 logical-GPIO
  findings without pretending that PCB continuity has been measured.
- `kb7-stock-flash.json` records hashes, ranges and independently derived format
  facts from two bit-identical owner-supplied 32-MiB reads. It contains no dump,
  log, firmware bytes or extracted asset.

## Current physical evidence — 2026-08-23

- The external device identifies as Macronix `MX25L25635F/MX25L25645G`
  (`c2 20 19`), and two complete main-array reads have the same SHA-256.
- `MCU_RST` measured about 3.2 V released and 0.2 V when asserted through 1 kΩ;
  continuity to the expected SoC lead and an SFC-idle waveform are still
  unmeasured.
- The CH341B PCB used for acquisition was later measured at approximately 5 V
  on CS. It is not considered electrically safe for further connection to this
  3.3-V flash without proper level translation.
- An ESP32-C3 full-stock restore/verification rehearsal restored normal boot.
  Leaving that programmer connected while unpowered interfered with boot, so
  every external bus master must be physically disconnected or demonstrably
  high-impedance before releasing reset.
- The V1.22 preserved loader completed one guarded `F6 18` + `F6 06`/`F6 15`
  marker cycle at `0x0008e000`; complete postflight reads found no unintended
  byte difference and the final image exactly matched the baseline.
- A second guarded cycle populated all 4,096 bytes of sector `0x000c6000` and
  immediate 512-byte guards on both sides. The normal-NOR `F6 15` operation had
  an exact observable 4-KiB programmed-data footprint at that target, cleanup
  restored the complete baseline, and the owner then confirmed a normal cold
  boot and working keyboard. This remains a one-unit/loader/target result;
  `F6 19`, other targets and interruption behavior are untested.

This demonstrates the development unit's external-SPI rollback path and two
bounded preserved-loader experiments. It does not prove the safety of
installing the replacement firmware or provide a general USB flasher. Raw
backups, programmer logs and repair images are intentionally not published or
included in this public repository.

Every factual item identifies its evidence class and source page. Page numbers
refer to Sonix *SNC7320 Series Data Sheet*, revision 2.1 (1 June 2022), whose
PDF SHA-256 is
`d360aca16c2695f12edf91d263b2994b36edf5ad6faf130547a9220dfaca94b4`.
PDF and printed page numbers coincide.

Evidence classes:

- `datasheet`: explicitly stated by the manufacturer;
- `firmware_recovery`: independently recovered from lawfully held reference
  firmware, summarized without copied code or vendor implementation addresses;
- `user_observation`: reported marking or PCB label;
- `inference`: a joined conclusion that still requires measurement; and
- `unverified`: a field reserved for a physical result that has not been
  collected.

The `SNC73200M1NLFG-000` package selection is conditional on the abbreviated
marking and must be verified from a complete package photograph. A different
part or package suffix invalidates package-lead numbers.
