# KB7 codebase review

Review date: 2026-08-18
Scope: full repository — `replacement_fw/`, `pc_app/` (Python package and web
studio), `docs/`, `tools/`, build and CI.
Method: independent read-only reviews of the firmware C, the Python studio, the
browser studio, documentation-vs-implementation consistency, and the test/build/CI
infrastructure, each cross-checked against the source and the format specs. All
findings below were verified against the code; no repository files were modified
during the review.

> **Historical snapshot.** This review describes the earlier stubbed tree at its
> 38-test baseline. The subsequent completion work addressed R1–R4, the live and
> latent F-series defects, the listed Python/browser correctness issues, CI
> enforcement, and the material coverage gaps. The current implementation and
> verification record are in `FIRMWARE-COMPLETION-2026-08-18.md` and
> `AUDIT-REMEDIATION-2026-08-17.md`; the original findings remain below as an
> audit trail rather than a description of current behavior.

## Repository at a glance

A deliberately non-flashable, source-only research prototype in two halves
(~6,200 lines):

- `replacement_fw/` — freestanding Cortex-M3/Thumb-2 firmware for an SNC7320-based
  KB7 keyboard. Two images (`core0`/`core1`) that both execute on Core 0 (the
  `0x10000000` region is a shared I-cache window, not a real second-core release —
  a documented open blocker). `core0` owns the vector table, SysTick, clock/DRAM/
  flash and publishes a function-pointer ABI at `0x18010000`; `core1` is the
  application superloop (USB, hall sensors, encoder, touch, a declarative UI parsed
  from A/B flash slots, and a host control-plane state machine).
- `pc_app/` — an offline, dependency-free configuration studio: a Python package
  (`kb7studio`: `KBS1` screen compiler, profile validator, HID-report/protocol
  model, NOR storage model, CLI) plus a browser editor (`web/app.js`, four
  workspaces). No device I/O by design.
- `docs/`, `tools/` — format specs and security audits, plus two publication-
  boundary guards (`check_public_tree.py`, `audit_firmware_source.py`).

Baseline confirmed at review time: 38/38 tests pass, `node --check` clean, both
audit tools pass, `make bundle` fails closed as intended.

## Overall assessment

The project's central safety claim — that this tree cannot actuate hardware and
cannot produce a flash image — genuinely holds in code, in layers: flash
erase/program return `-1` unconditionally and every mutation path checks it; USB
init/send fail; keymap lookup always fails; hardware feature gates are
`#if`-compiled-out (not merely branched around); and the host-server receive path
is never called from firmware. The wire formats have byte-for-byte parity across
docs, C, Python, and JS on the 64-byte host report, the `KBS1` header/records, and
the storage headers, and the CRC-32 is identical across all four. The 2026-08-17
audit remediations check out where claimed.

The findings fall into two buckets: latent firmware defects the stubs currently
mask (they go live the moment the stubs are filled in), and live issues in the
studio and infrastructure that bite today.

---

## Priority 1 — act on soon

### R1. DOM-XSS in the web studio (live, exploitable). Severity: critical.
Files: `pc_app/web/app.js:1216-1224`, `app.js:247`, `app.js:278`;
`pc_app/web/index.html` (no CSP).

The raw `kb7-screen-v1` JSON import path assigns imported data to the global `doc`
*before* validation, unlike the `.kbs` path (validate-inside-`parseBinary`) and the
profile path (`loadProfile`, rollback on failure). Two render sites interpolate
screen/widget color fields into `innerHTML` without `esc()`:

- `app.js:247` — `style="background:${item.background}"`
- `app.js:278` — `...;background:${widget.foreground}`

A crafted color such as `#000"><img src=x onerror=...>` fails `validateScreens()`
(so the import surfaces a failure toast), but `doc` has already been overwritten.
The next Display re-render (e.g. clicking the active Display tab, or "Reset view")
injects the payload verbatim, executing script in the app's own origin. With no CSP
meta tag the injected script is unsandboxed and could perform the network/device
I/O the app promises never to do.

Fix: validate a local value and commit to `doc` only on success (mirror the `.kbs`/
profile pattern), and route `item.background`/`widget.foreground`/`widget.background`
through `esc()` or the color-pattern check before any `innerHTML`/`insertAdjacentHTML`.

### R2. CI does not enforce the safety boundary. Severity: critical.
Files: `.github/workflows/ci.yml`, root `Makefile`, `tools/audit_firmware_source.py`.

CI runs only `check_public_tree.py`, the Python unittest suite, and `node --check`.
It never installs an ARM toolchain, never runs `firmware-check` (cross-compile
core0/core1, `verify`, `audit-profile`), and never runs `audit_firmware_source.py`.
That audit script is the only automated check that would catch a reintroduced
legacy report ID, a re-armed `timeout--` loop, `kb7_usb_init()` returning `true`, or
a `KB7_ENABLE_*` flag flipped to 1 — and it runs only on developer discipline. A PR
reintroducing any such regression, or simply breaking the ARM build, shows green CI.

Fix: add `apt-get install -y gcc-arm-none-eabi`, run
`make -C replacement_fw clean all audit-profile clean`, and run
`python3 tools/audit_firmware_source.py .` in `ci.yml`.

### R3. `check_public_tree.py` is bypassed by encoded binary content. Severity: critical (for its stated purpose).
File: `tools/check_public_tree.py:40-79`.

The tool flags files by known filename, denied extension/parent, file-magic
(ELF/PE/ZIP/7z only), UTF-8 decode failure, or three literal text markers. Any
binary re-encoded as base64/hex text in a `.txt`/`.md` passes every check (verified
with a base64 chunk of a real binary → `"passed": true`). The `DENIED_TEXT` markers
are exact substrings, defeated by any reformatting. The tool remains useful for
catching *accidental* artifact commits, but its docstring overstates the guarantee.

Fix: describe it as an accident-catcher, not a leak-preventer; consider entropy/
base64-density heuristics if deliberate-leak protection is actually a goal.

### R4. ENTER_LOADER (`0x7e`) — weaker than documented, misreports status, untested, absent from the Python model. Severity: high.
Files: `replacement_fw/core1/host_server.c:298-307`; `docs/HOST-PROTOCOL.md:53`;
`pc_app/kb7studio/protocol.py`; `replacement_fw/tests/host_server_host.c`.

Four converging problems:
- The doc specifies "a second confirmation token/session," but the code reboots the
  device into the loader on a single 64-byte report (flags `0xa5`, token
  `0x4b42374c`, `"ENTERKB7"`). Frame CRC is integrity, not authentication — one
  spoofed report reboots the keyboard out of its application.
- `status` is set to `KB7_HOST_STATUS_BAD_STATE` unconditionally after the match
  block, so even a valid confirmation returns `BAD_STATE`.
- The opcode is absent from `protocol.py`'s `OfflineReceiver` (would fall through to
  `UNSUPPORTED`).
- No test exercises either branch — including the critical negative path (near-miss
  token must not call `enter_loader()`).

Fix: reconcile code, doc, Python model, and tests together — implement the two-step
confirmation (or correct the doc), return a correct status, and add both-branch
coverage with a test double asserting non-invocation on a near miss.

---

## Priority 2 — firmware lifecycle defects (latent behind stubs)

These are real logic defects that the fail-closed stubs currently mask. They become
live exactly when the project's remediation plan fills the stubs in, so they should
be fixed before that happens.

### F1. Live UI store never invalidated when its backing flash is erased. Severity: high (latent).
Files: `replacement_fw/core1/main.c:89-96`; `host_server.c:78-98,201-203`;
`ui/screen_parser.c:215-221`; `ui/renderer.c:114-121,154-158`.

`core1` parses the boot-selected slot and keeps `screens.header`/`screens.bytes`
pointing into XIP flash for the session. A second upload (BEGIN targets the other
slot, which may be the runtime-active one) or a factory reset erases that memory out
from under the live store. Accessors then re-read `screen_count = 0xffff` and
`screens_offset = 0xffffffff` from erased flash and dereference
`bytes + 0xffffffff` — unbounded reads from the render/touch paths. Validation
results are cached; the validated bytes are not.

Fix: invalidate or reload the runtime store on commit/factory-reset/BEGIN, or render
from a RAM copy.

### F2. Screen change mid-touch swallows the release phase — stuck HID/media key. Severity: medium (latent).
Files: `ui/renderer.c:184-190,138`; `core1/main.c:36-39`; `core1/usb_client.c:26-39`;
`host_server.c:291`.

`kb7_ui_navigate` unconditionally clears `active_widget`, and is reachable
asynchronously to touch via host `STORE_SELECT`. Holding a `HID_KEY` widget when a
SELECT arrives means the finger-release UP phase is never dispatched, so the key
stays pressed indefinitely (same for `MEDIA_KEY`). The main loop's lost-frame
failsafe does not cover this path.

Fix: `kb7_ui_navigate` should dispatch the active widget's UP action before clearing
it.

### F3. Lost host session permanently wedges the updater. Severity: medium (latent).
Files: `host_server.c:55,263,277-278`.

A host that crashes mid-transfer leaves `receiving` true forever (no timeout,
despite the documented ABORT/reset/timeout edge). A new session gets `BAD_STATE` on
BEGIN and on ABORT with any other id, and the stale `transfer_id` is never disclosed
(`reply()` echoes the command's id), so the correct ABORT cannot be constructed.

Fix: allow ABORT with `transfer_id == 0` as a forced reset, expose the current id,
or add an inactivity timeout.

### F5. Per-command full-slot CRC and multi-sector erase inside the superloop. Severity: medium (robustness/latency, latent).
Files: `core1/storage.c:70-76`; `host_server.c:178,93-98`.

`kb7_storage_select()` re-validates both slots' payload CRCs (up to 2 MiB each, in
128-byte chunks) on every call, and it is called per STORE_READ and per BEGIN; BEGIN
additionally erases up to 512×4 KiB sectors synchronously. Reading a 2 MiB store in
36-byte chunks implies on the order of 230 GB of flash reads. During all of this the
loop cannot scan keys, feed touch, or send reports, and there is no watchdog.

Fix: cache the boot-time slot selection (invalidated per F1) rather than
re-validating per command.

### F4-loader NULL-call note. Severity: medium (latent).
File: `host_server.c:298-307` vs `:60-64`.

The ENTER_LOADER branch calls `kb7_runtime()->enter_loader()` without the magic/NULL
guard the flash paths use via `runtime_flash_available()`. Currently prevented by the
init-time check at `core1/main.c:135`, but it is an inconsistency worth closing.

### F6-F11. Lower-severity firmware items.
- F6 (low, latent): zero-length TRANSFER_WRITE at `offset == total_length` passes all
  checks and issues `flash_program(..., 0)`; should be `BAD_STATE`
  (`host_server.c:119-125`).
- F7 (low): quadrature decoder shifts history every poll, so detent detection is
  cadence-dependent; shift only on sample change (`drivers/encoder.c:17-30`).
- F8 (low, latent): screen actions can set actuation 0 / rapid-trigger delta 0,
  making every key always-pressed; enforce sane minimums at parse time
  (`ui/screen_parser.c:49-54`, `core1/main.c:75-82`, `drivers/hall_policy.c:17,35`).
- F9 (low): core1 ABI-mismatch path spins in `for(;;) kb7_wfi()` with no recovery;
  could set the loader flag and reset (`core1/main.c:135-138`).
- F10 (low): stuck keys when MCU2 fails mid-press — last report stands until the link
  recovers; consider an empty report after N failures (`core1/main.c:112-131`).
- F11 (low, informational): `offset > KB7_FLASH_SIZE` should be `>=`
  (`drivers/flash.c:7`); dead code at `host_server.c:81-83`; geometry validated
  against literals `480U`/`800U` instead of `KB7_DISPLAY_WIDTH/HEIGHT`
  (`ui/screen_parser.c:187-188`); `text()` x-advance can wrap `int16_t` on a
  ~4,680-char label (cosmetic, every pixel is clipped).

Documented known blockers confirmed still present (not new findings): SysTick reload
assumes an unproven 120 MHz clock; GPIO function/MUX encoding contradicts the
datasheet; the second physical M3 core is assumed quiescent; COMMIT verifies via the
XIP window with unproven command/XIP coherency.

---

## Priority 3 — studio correctness and parity

### Python (`pc_app/kb7studio/`)
- Medium: `rgb565()` accepts JSON booleans as colors — `isinstance(True, int)` with
  no bool guard, unlike every other validator; `background: true` silently compiles
  as `1` (`format.py:40-44`).
- Medium: `transfer_reports()`/CLI `protocol-plan` produce plans the project's own
  `OfflineReceiver` rejects (no min-48/max-capacity bound), and `compile_document`
  accepts documents exceeding the 2 MiB slot (`protocol.py:65-77` vs `:123`).
- Medium/high: the CLI has no exception handling and no tests — missing file, bad
  JSON, and out-of-range `--transfer-id` all crash with a raw traceback
  (`cli.py`; no `tests/test_cli.py`).
- Low: `crc32()` duplicated identically in three modules
  (`format.py:36-37`, `protocol.py:26-27`, `storage.py:15-16`); hardcoded limits in
  `protocol.py:112-116,123` that can drift from `format.py`; dead `compile_file`/
  `load_profile` (`format.py:295-297`, `profile.py:219-222`); `canonical_profile()`
  doesn't canonicalize the embedded screen document; misleading per-key error
  message (`profile.py:137-140`).

### Browser (`pc_app/web/app.js`) — JS/Python parity
- High: raw-import path doesn't recompute `nextId` → widget-ID collisions on the
  normal export→import round trip, unfixable via the UI (no ID field)
  (`app.js:1216-1224`).
- High: JS `validateProfile()` accepts analog deadzone/saturation combinations Python
  rejects — JS omits the independent `saturation >= 0.1` / `deadzone <= travel-0.1`
  bounds (`app.js:849` vs `profile.py:164-167`).
- Medium: `rgb888()` decode rounds (`Math.round`) where Python floors (`//`); 15 of
  32 channel values differ, so colors drift between the two tools across round trips
  (`app.js:780-785` vs `format.py:54-58`).
- Medium: `addWidget()` clamps only the upper x/y bound, so an edge-drop creates a
  negative-coordinate widget that fails export (`app.js:417-428`).
- Low: inspector fields have no label/input association (accessibility); design canvas
  is pointer-only despite `tabindex="0"`; `#formatHealth` sticks on "Error"; no undo
  or confirmation on destructive actions.

---

## Priority 4 — documentation and test coverage

### Documentation (high quality overall)
- High: `PROFILE-FORMAT.md:113-115` — the "1,519-packet replay" and four specific
  Arrow-preset HID codes are backed by nothing in the repo and contradict the doc's
  own `device-mapping-not-included` capability record.
- Medium: `STORAGE-MAP.md:55` describes a "256-byte page" commit the code doesn't do
  (writes are <=36-byte direct programs); the profile/crash wear-leveling regions
  (`STORAGE-MAP.md:70-73`) are written in present tense but aren't implemented.
- Medium: `AUDIT-REMEDIATION-2026-08-17.md:82-86` recorded `core1` build sizes don't
  reproduce (+32/+40 bytes) with `arm-none-eabi-gcc 13.2.1`; likely libgcc drift, but
  presented as a fixed verification record without noting toolchain sensitivity.
- Low: `HOST-PROTOCOL.md` conflates bad-report-ID into `BAD_VERSION`; CRC-32 variant
  named in `SCREEN-FORMAT.md` but only "CRC-32" elsewhere; `OfflineReceiver` hardcodes
  the QUERY_VERSION reply; a couple of implementation-only analog/per-key bounds are
  undocumented.

### Test coverage gaps (prioritized)
1. `drivers/hall_policy.c` — rapid-trigger state machine and wrap-around peak/valley
   arithmetic (pure logic, trivially host-testable) has no test at all.
2. Real `core0/usb.c` and `drivers/flash.c` fail-closed behavior is asserted only by
   brittle literal-string matches in `audit_firmware_source.py`, never by an
   executable test; `host_server_host.c` mocks flash rather than compiling the real
   driver, so its bounds checks are never exercised.
3. `host_server.c` gaps: double-BEGIN (`BAD_STATE`), commit CRC mismatch,
   QUERY_VERSION/QUERY_CAPABILITIES, and both ENTER_LOADER branches.
4. `drivers/touch.c` I2C bit-bang state machine (177 lines) is untested.
5. `core1/main.c` `action()` dispatcher and `process_hall()` glue are untested.
6. `mcu2.c` `KB7_MCU2_BAD_FRAME` branch and `kb7_mcu2_read_normalized`; `gpio.c`/
   `encoder.c` register/quadrature logic.
7. `pc_app/kb7studio/cli.py` has no tests.
8. Extend `audit_firmware_source.py` to assert `rgb.c`/`lcd.c`/`keymap.c` return
   values, not just `usb.c`/`flash.c`/`touch.c`.
9. Add a Python `OfflineReceiver` ↔ C `host_server` parity test, mirroring the
   existing screen-parser parity fuzz test.
10. `test_no_device_io.py` uses non-recursive globs; switch to `rglob` for durability.

---

## What checked out clean (confirmed, not just read)

- Fail-closed publication boundary genuinely enforced in code (flash/USB/keymap
  stubs, `#if`-gated peripherals, host receive path never called).
- Wire-format parity across docs/C/Python/JS: 64-byte host report and CRC scope
  (bytes 1..59), 48-byte `KBS1` header, 16-byte screen record, 40-byte widget record,
  64-byte slot header — byte-for-byte.
- CRC-32 identical across all four implementations (poly `0xedb88320`, init
  `0xffffffff`, final XOR; matches `zlib.crc32`).
- Screen parser: strict layout, overflow-safe range checks, duplicate-ID checks,
  per-action argument ranges, HID usage whitelist, strict UTF-8, CRC-before-trust,
  bounded widget indexing.
- Storage: WRITING→VALID single-bit NOR transition, header-CRC-with-state-zeroed
  trick implemented identically on writer and reader, payload CRC validated before
  slot selection, wrap-safe generation comparison.
- Startup/linkers: 79-entry vector table enforced by linker + Makefile,
  ALIGN(4)-bracketed `.data`/`.bss`, non-overlapping regions with overflow ASSERTs.
- The C host tests compile the actual firmware sources (not stand-ins) under
  `-std=c11 -Wall -Wextra -Werror`; the ARM build is warning-clean; `make bundle`
  fails closed (exit 2, no objcopy path); the 2026-08-17 remediations match source.
- No device I/O anywhere in `pc_app/`; both sample profiles validate; all 38 tests
  pass.

None of these findings change the non-flashable verdict. Priorities R1-R4 are worth
acting on soon; the F-series should be tracked against the remediation plan so they
are fixed before the stubs are filled in.
