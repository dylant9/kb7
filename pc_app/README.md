# Offline Control Studio

Offline Control Studio is a dependency-free profile editor and simulator. It has
four workspaces:

- **Display** — design a 480×800 screen, trace pointer/touch gestures as a
  joystick model, and export canonical JSON or `KBS1`.
- **Lighting** — preview effects, zones, per-key colors, brightness, and speed.
- **Switches** — model global/per-key actuation and Rapid Trigger behavior.
- **Analog** — bind logical keys to X/Y axes and simulate response curves.

Open `web/index.html` directly in a modern browser. The project stores drafts in
browser-local storage and contains no HID, USB, serial, programmer, network, or
device-discovery code.

Current status: JSON, `KBS1` and `KBP1` validation/compilation are implemented
and tested for up to five persistent profiles. Screen artifacts are capped to
the current 1.25-MiB slot payload and profile artifacts to the five-record KBP1
limit. The studio remains deliberately offline; it neither discovers the KB7
nor sends the loader's USB/SCSI flash commands.

Display **Touch Trace** mode records native coordinates, pressure when the
browser supplies it, pointer sample rate and timing gaps, plus normalized X/Y
joystick output with a configurable radial deadzone. Trace JSON is explicitly a
browser-input measurement; it does not measure the physical display controller,
firmware latency, or USB transport.

The Python package is the canonical offline validator/compiler:

```sh
PYTHONPATH=. python3 -m kb7studio.cli compile samples/offline-example.json example.kbs
PYTHONPATH=. python3 -m kb7studio.cli inspect example.kbs
PYTHONPATH=. python3 -m kb7studio.cli profile-check samples/offline-example-profile.json
PYTHONPATH=. python3 -m kb7studio.cli profile-compile samples/offline-example-profile.json example.kbp
PYTHONPATH=. python3 -m kb7studio.cli profile-inspect example.kbp
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The suite also host-compiles selected firmware modules. It checks exact
Python/C parser parity, recovered clock and MCU2 semantics, UI/report behavior,
and the A/B updater against a fixed-address simulated NOR device. No test opens
a physical device.

The compiler includes the recovered 85-key logical/HID routing model and can
emit one-to-five persistent Hall/analog/global-lighting profiles, layout
variants, initial modes, and complete Primary/Game/Easy-Shift/FN1 action-table
overrides. Logical-key→LED channel
correlation is still absent, so nonempty per-key RGB is rejected rather than
silently misaddressed. Simulator output is not a claim of working hardware.

See `../docs/PROFILE-FORMAT.md`, `../docs/SCREEN-FORMAT.md`,
`../docs/HOST-PROTOCOL.md` and `../docs/STORAGE-MAP.md`.
