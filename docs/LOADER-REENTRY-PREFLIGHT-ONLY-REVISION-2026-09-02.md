# Loader-reentry preflight-only revision

Branch `loader-reentry-preflight-only`, rebuilt on 2026-09-03 (second rebuild, after the live-region continuity change) on top of the
hardware-validation branch after the read-reliability gate pass, the
backend-lock hardening, the N6/N8/N9 closures, the post-image live-region
policy, the F1 proof-startup change with its campaign regeneration and the live-region continuity rules.

## What this revision enables

Exactly one thing: `LIVE_READ_ONLY_PREFLIGHT_ENABLED = True` for the exact
reviewed campaign `1ce62e95ee2c6c84b5abb8996f7964bacae661869152ead20f5c7138b2b0b508`.
`LIVE_PROOF_CAMPAIGN_ENABLED` stays false, so `step`, `validate-reentry` and
`finalize --commit` are refused in the CLI, in every live entry point and inside
both USB backends. The policy descriptor records
`read_only_preflight_diagnostic_authorized: true` and
`fixed_proof_hardware_test_authorized: false`; the source audit requires each
gate to be exactly one constant assignment in exactly this state; the hardware
JSON and facts checker carry the same authorization block.

Pins in this revision: policy `11587216a222a730ed915e9e698ab8c45880c4bda2d83ff8cebbdd988862bb54`, executor descriptor `5e599f200fe8dc9de4b398e116ee76db2c7ebbe50eabb034af32c486bed79d6b`,
executor source `f2052027304243d6bf0583e7862f1644736a6e0182fb66cac2d1c76fd084a4f1`.

## What the preflight does

`kb7-loader-reentry-executor.py preflight --commit` opens `10f5:5037` with the
read-only transport (no clear-halt, strict close), takes two complete 32 MiB
reads through the loader, requires them identical to each other, requires the
region below the post-image live region (`0x0156b000`) byte-exact against the
reviewed baseline, records the live region's hash, verifies loader identity
and USB topology, and publishes the journal at `boundary_verified` index 0.
No program or erase command is representable in that transport. A difference
confined to the live region, such as the stock settings record rewrite seen on
2026-09-02, no longer stops the preflight; it is recorded.

Exit codes: 0 verified; 2 locked or invalid invocation before USB; 3 external
SPI required (post-intent classes, not reachable from preflight); 4 state
inspection required; 5 transport or strict-close stop, power-cycle before a new
journal; 6 stable USB image differs from the baseline below the live region,
verify independently before any write.

## Operator notes

- After an exit 5 or 6 the `preflight_started` journal remains and `preflight`
  refuses an existing journal: move it aside as a record, never delete it, and
  use a new journal path after the power-cycle.
- A journal produced by this revision binds `executor_source_sha256 = f2052027304243d6bf0583e7862f1644736a6e0182fb66cac2d1c76fd084a4f1`;
  any later revision, including a mutation-enabled one, rejects it and must run
  its own preflight. A pass here is not a reusable boundary.
- Operating conditions as in the read-reliability record: external programmer
  physically detached, NOR lead stubs at ~20 mm, exactly one `10f5:503d` hub
  and one keyboard on the bus, no mass-storage mount, ISP entered by the vendor
  HID mode-switch, two distinct byte-identical owner baselines and the private
  campaign directory generated from them by the campaign builder.

## What a pass permits

Only preparation and separate review of a mutation-enabled revision. A pass
here installs nothing.
