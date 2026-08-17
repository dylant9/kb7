# KB7 Studio

KB7 Studio is an offline, dependency-free profile editor and simulator. It has
four workspaces:

- **Display** — design a 480×800 screen and export canonical JSON or `KBS1`.
- **Lighting** — preview effects, zones, per-key colors, brightness, and speed.
- **Switches** — model global/per-key actuation and Rapid Trigger behavior.
- **Analog** — bind logical keys to X/Y axes and simulate response curves.

Open `web/index.html` directly in a modern browser. The project stores drafts in
browser-local storage and contains no HID, USB, serial, programmer, network, or
device-discovery code.

The Python package is the canonical offline validator/compiler:

```sh
PYTHONPATH=. python3 -m kb7studio.cli compile samples/neon-control.json neon.kbs
PYTHONPATH=. python3 -m kb7studio.cli inspect neon.kbs
PYTHONPATH=. python3 -m kb7studio.cli profile-check samples/neon-control-profile.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Device-specific selector and LED mappings are deliberately absent. Profiles
record that boundary as `device-mapping-not-included`; simulator output is not a
claim of working hardware integration.

See `../docs/PROFILE-FORMAT.md` and `../docs/SCREEN-FORMAT.md`.
