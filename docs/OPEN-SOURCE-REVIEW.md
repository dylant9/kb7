# Public-source provenance review

Review date: 2026-08-17; remediation additions reviewed 2026-08-18
Scope: this repository directory only

## Decision

This directory is a conservative public-release candidate. It contains
independently authored source, tests, project-owned formats, and documentation.
It does not contain vendor firmware or copied vendor source. Publication should
still receive a human rights-holder and jurisdiction-specific legal review;
this engineering review is not legal advice and cannot guarantee rights that
the contributor does not possess.

## Included

- Independently authored C firmware architecture and application logic.
- Independently authored Python/JavaScript/HTML/CSS offline tooling.
- Tests (including independently authored host-side C harnesses) and original
  JSON examples.
- Project-defined screen, profile, host-control, and storage formats.
- This provenance record and the source-code security audit.
- An independently written datasheet audit and derived interoperability pin
  map; no Sonix PDF, diagram, or copied vendor table is included.
- Apache-2.0 license and project/trademark notice.

No external scripts, fonts, images, packages, or vendored libraries are bundled.

## Sanitized in the public copy

- The exact panel initialization stream and LCD-controller profile were replaced
  by a fail-closed stub.
- Recovered RGB topology/controller packets were replaced by a fail-closed stub.
- The captured Hall-selector table was removed from the studio.
- The USB VID/PID, descriptors, and unvalidated controller initialization were
  replaced by a fail-closed transport stub.
- Flash-image and stock-region bundle generation was removed; `make bundle`
  deliberately fails.

## Excluded and retained only in the private workspace

- All Turtle Beach/Sonix/MCU vendor firmware, loaders, manifests, asset regions,
  installers, DLLs, and archives.
- Third-party datasheet/manual PDF files, whose redistribution terms are not
  granted by this repository.
- ELF/object/raw/padded binaries, maps, disassemblies, Ghidra projects, and
  decompiler output.
- USB/SPI/I2C captures, screenshots or assets extracted from vendor software,
  private raw pin-map evidence, ROM traces, and decompiler-level reports.
- The stock-core patch experiments and their exact vendor function addresses.
- Firmware repackers, manifests, flash plans, and incomplete flash prefixes.
- The separate `kb7-linux` tree, which currently says all rights reserved and
  has no redistribution license.

## Engineering checks

- A normalized 24-token source comparison checked 47 candidate source files
  against privately held decompiler exports for two firmware versions and the
  secondary controller: zero exact windows matched. This is useful evidence
  against verbatim copying, not a legal conclusion.
- The public-tree checker rejects symlinks, generated/build directories,
  executable/archive/firmware extensions, binary magic, non-UTF-8 files, and
  known private artifact names.
- The browser source has no external URL, font, image, or package dependency.
- Generated files are ignored and are not included in the publication manifest.

## Legal basis considered

The U.S. Copyright Office states that copyright protects program expression but
not ideas, program logic, algorithms, systems, methods, concepts, or layouts:
<https://www.copyright.gov/register/tx-programs.html>.

17 U.S.C. §1201(f) provides a conditional interoperability reverse-engineering
exception for a person who lawfully obtained the right to use a program, and
conditionally permits necessary interoperability tools:
<https://www.law.cornell.edu/uscode/text/17/1201>.

OpenAI's current Terms state that, as between the user and OpenAI and to the
extent permitted by law, the user owns Output:
<https://openai.com/policies/terms-of-use/>.

Those sources do not establish that every jurisdiction, contract, patent,
trademark, trade-secret situation, or contributor history is clear. Before a
public push, the repository owner must confirm lawful possession of the original
device/software, authority to license contributed work, applicable contract
terms, and the selected Apache-2.0 license.

## Publication rule

Publish only this directory—not its parent workspace. Run:

```sh
python3 tools/check_public_tree.py .
python3 tools/audit_firmware_source.py .
git status --short --ignored
```

Review every new file and the entire Git history before adding a remote.
