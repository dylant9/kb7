# Public-source provenance review

Review date: 2026-08-17; remediation additions reviewed 2026-08-18; full-flash
and public-repository status reviewed 2026-08-22; bounded USB-ISP and fixed
scratch-executor results plus stock loader-reentry evidence reviewed 2026-08-23
Scope: this repository directory only

## Decision

This directory is the public, source-only project tree. It contains independently
authored source, tests, project-owned formats, and documentation. It does not
contain vendor firmware or copied vendor source. New contributions and releases
should still receive a human rights-holder and jurisdiction-specific legal
review; this engineering review is not legal advice and cannot guarantee rights
that the contributor does not possess.

## Included

- Independently authored C firmware architecture and application logic.
- Independently authored Python/JavaScript/HTML/CSS offline tooling.
- Tests (including independently authored host-side C harnesses) and original
  JSON examples.
- Project-defined screen, profile, host-control, and storage formats.
- Independently authored clean-room panel, RGB, USB-controller, Hall-routing
  and input implementations expressed from interoperability facts; no vendor
  source text or firmware bytes are included.
- This provenance record and the source-code security audit.
- An independently written datasheet audit and derived interoperability pin
  map; no Sonix PDF, diagram, or copied vendor table is included.
- Original machine-readable SoC and package-pin facts with page-level
  provenance, confidence classes, and unverified continuity fields.
- Independently derived full-flash hashes, ranges, format observations and
  recovery measurements. No raw dump, programmer log or repair image is
  included.
- Independently authored loader-reentry verifier logic, a clean-room 84-byte
  stackless relocation bridge and 72-byte loader-copy blob, minimal
  interoperability hashes/offsets in
  `hardware/kb7-stock-loader-reentry.json`, and the prose evidence boundary in
  the [stock loader-reentry proof](STOCK-LOADER-REENTRY-2026-08-23.md). The
  offsets identify only the request, relocation, reset and marker-consumer facts
  needed to reproduce the protocol; no stock instruction bytes, raw binary,
  disassembly or decompiler output is included.
- Independently authored fixed proof-campaign and owner-campaign-bound executor
  source, currently locked pending the read-reliability gate.
  The builder derives a checksum-valid clean-room Core 0 plus exact stock Core 1
  and an exact-stock reverse sequence; the executor exposes no raw flash fields
  and pins the independently rederived owner campaign identity. Later evidence
  separates a SPI-confirmed two-byte physical corruption from a post-restore
  command-aligned USB acquisition failure. Both proof preflight and mutation
  are now locked. The public machine record includes only hashes, operation
  counts, fixed geometry, bounded authorization flags and the hardware-unrun
  proof boundary. Private campaign descriptors, sector images,
  baselines and journals remain excluded. See the
  [fixed proof campaign](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md) and
  [read-reliability incident](USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md).
- Independently authored external-SPI recovery helpers, read-only USB-ISP
  diagnostics, two guarded dry-run-default USB write-path validation
  experiments, a separate fixed dry-run-default scratch executor, and
  clean-room summaries of the F6 interoperability findings. The scratch
  executor can derive only its 22 reviewed non-firmware operations. Its v1 plan
  completed once on the development unit, restored the exact 32-MiB baseline,
  and returned to operator-reported normal keyboard operation. Its historical
  v2 plan also completed once: its mandatory command-complete/no-postread
  active-intent checkpoint reconciled the exact postimage in a fresh process
  over a mutation-incapable backend, then the fixed cleanup restored the exact
  baseline and the keyboard returned to normal operation. Its current v3 plan
  has also completed once; it fixes an abrupt self-`SIGKILL` after validated
  program CSW and durable/read-back command-complete state, before WIP polling, postread
  or explicit USB close. Preflight-started and raw-intent markers are published
  before backend construction or USB and are terminal if left visible. Only
  exact command-complete and final-complete states are reconcilable; each
  consumes a one-shot started state before USB and closes strictly before final
  publication. Atomic ambiguity permits only local inspection, never USB.
  Status 137 is operator-observed and not journal-bound. The v3 run observed
  that status, rejected a duplicate step before USB, reconciled the exact
  postimage without replay, restored the baseline and returned to operator-
  confirmed normal `5038` keyboard operation. The public tree
  records only independently authored source, hashes, classifications and
  summarized results from those runs. No vendor DLL, disassembly listing, general USB
  firmware flasher, raw transcript, capture, journal or stock byte payload is
  included.
- Independently authored offline Ed25519 bundle-authentication source and
  tests. It signs only after complete planner revalidation and cannot authorize
  a write. No private key, public release key, trust fingerprint, generated
  signature envelope, bundle, baseline, or payload is included.
- Apache-2.0 license and project/trademark notice.

No external scripts, fonts, images, packages, or vendored libraries are bundled.

## Sanitized in the public copy

- No vendor implementation, decompiler listing, symbol names, extracted
  descriptors, firmware bytes, captures or assets are published. The C source
  is independently authored and tests project-owned behavior.
- The USB identity is zero by default. No Turtle Beach or other third-party
  VID/PID is appropriated, and controller attach remains behind an explicit
  board-verification gate.
- Per-key RGB names are not guessed: only stable controller positions and
  packet framing are present until physical correlation is measured.
- Flash mutation defaults off and is allow-listed to project-owned A/B stores.
  The ordinary `make bundle` target deliberately fails.
- The older source-only manifest-changing constructor is retained as an audit
  artifact and must not be treated as an executable update plan. The newer
  V1.22-only paired planner accepts two owner-supplied full captures and emits
  only clean replacement sector images plus offline metadata. It preserves the
  manifest, contains no device I/O, never emits a full stock image and remains
  execution-unapproved. A separate source-only paired-firmware executor
  scaffold exposes only read-only preflight/reconciliation; its live mutation
  adapter is hard-disabled and no execute command exists. The distinct scratch
  executor accepts no firmware bundle or caller-selected address, CDB, payload
  or operation. Its current v3 checkpoint is fixed in the hash-bound plan
  rather than exposed as a runtime selector. The completed v2 plan remains a
  historical validation record. Neither changes the paired executor's lock.
- The default-off loader-reentry proof is a local build profile, not an
  installable image. Its ELF is only planner-compatible; the ordinary Makefile
  still cannot emit a bundle, and the paired-firmware executor remains
  mutation-locked. The separate fixed proof executor now pins the independently
  rederived private campaign ID and is live only for that exact bounded
  install/restore test. It does not authorize a general device run or host
  recovery opcode.

## Excluded and retained only outside the public repository

- All Turtle Beach/Sonix/MCU vendor firmware, loaders, manifests, asset regions,
  installers, DLLs, and archives.
- Third-party datasheet/manual PDF files, whose redistribution terms are not
  granted by this repository.
- ELF/object/raw/padded binaries, maps, disassemblies, Ghidra projects, and
  decompiler output.
- USB/SPI/I2C captures, screenshots or assets extracted from vendor software,
  raw pin-map evidence, ROM traces, and decompiler-level reports.
- Stock-core patch experiments, raw function listings, instruction-byte
  sequences and full vendor symbol maps. Minimal hash-pinned interoperability
  offsets and verifier predicates are included as described above; raw
  binaries, disassembly and decompiler output remain excluded.
- Generated manifests, full-image-bound plans, proof-campaign descriptors and
  simulations, sector images, paired/proof/scratch executor journals,
  scratch-restart state, prefixes and any package containing stock bytes.
- Updater authentication envelopes and private signing keys. A reviewed public
  key/fingerprint may be considered only after the release trust policy is
  separately approved.
  Independently authored
  planner/checker/executor source is included; its generated state stays
  owner-local.

## Engineering checks

- A normalized 24-token source comparison checked 47 candidate source files
  offline against lawfully held reference analyses for two firmware versions
  and the secondary controller: zero exact windows matched. This is useful
  evidence against verbatim copying, not a legal conclusion.
- The public-tree checker rejects symlinks, generated/build directories,
  executable/archive/firmware extensions, binary magic, non-UTF-8 files, known
  prohibited artifact names, and conspicuously large base64/hex blocks. It is an
  accident detector, not proof against deliberately concealed content; human
  provenance and staged-diff review remain mandatory.
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
trademark, trade-secret situation, or contributor history is clear. Before
accepting or publishing new work, the repository owner must confirm lawful
possession of the original device/software, authority to license contributed
work, applicable contract terms, and the selected Apache-2.0 license.

## Public-repository rule

Treat every commit and push as publication. Work only in this directory—not its
parent workspace—and run:

```sh
python3 tools/check_public_tree.py .
python3 tools/audit_firmware_source.py .
git status --short --ignored
```

Review every new file and staged change before pushing. Review imported history
in full before merging it or publishing a release.
