# Contributing

Contributions are welcome, but this repository has an unusually strict source
boundary.

1. Do not submit vendor firmware, extracted assets, captures, decompiler output,
   disassembly, generated flash images, or code copied from a proprietary SDK.
2. Submit independently authored source and identify every external reference
   used to establish a functional interface.
3. Do not add a USB VID/PID, panel command profile, LED topology, key-selector
   map, or device write path without documented redistribution rights and
   hardware evidence.
4. Keep all hardware mutations default-off and fail-closed.
5. Run `make check` and include new tests for behavior changes.
6. Add an SPDX identifier or document the license of every third-party file.

Security-sensitive hardware changes require review against
`docs/SECURITY-AUDIT-2026-08-17.md`.
