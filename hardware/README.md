# Hardware evidence artifacts

These files are independently authored, machine-readable interoperability
summaries. They do not contain the Sonix PDF, vendor firmware, decompiler
output, PCB captures, or copied vendor tables.

- `snc7320-soc.json` records datasheet-confirmed architecture, memory, MMIO
  block bases, interrupts, DMA windows, clock/electrical limits, and known
  document inconsistencies.
- `kb7-pin-map.json` joins package-lead facts to clean-room KB7 logical-GPIO
  findings without pretending that PCB continuity has been measured.

Every factual item identifies its evidence class and source page. Page numbers
refer to Sonix *SNC7320 Series Data Sheet*, revision 2.1 (1 June 2022), whose
PDF SHA-256 is
`d360aca16c2695f12edf91d263b2994b36edf5ad6faf130547a9220dfaca94b4`.
PDF and printed page numbers coincide.

Evidence classes:

- `datasheet`: explicitly stated by the manufacturer;
- `firmware_recovery`: independently recovered from lawfully held reference
  firmware, summarized without copied code or private addresses;
- `user_observation`: reported marking or PCB label;
- `inference`: a joined conclusion that still requires measurement; and
- `unverified`: a field reserved for a physical result that has not been
  collected.

The `SNC73200M1NLFG-000` package selection is conditional on the abbreviated
marking and must be verified from a complete package photograph. A different
part or package suffix invalidates package-lead numbers.
