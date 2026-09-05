# Region-1 preflight-only revision

Branch `region1-reentry-preflight-only`, built on 2026-09-05 on top of the
`region1-reentry-offline` head after the independent review of that branch
(CLEAN WITH NON-BLOCKING NOTES) and the closure of its notes.

## What this revision enables

Exactly one thing: `LIVE_READ_ONLY_PREFLIGHT_ENABLED = True` for the exact
reviewed region-1 campaign
`9a582f1cf35ccb219d5477299ece6caa1285fcbff448e7901fdcaaae83e5c267`.
`LIVE_PROOF_CAMPAIGN_ENABLED` stays false, so `step`, `validate-reentry` and
`finalize --commit` are refused in the CLI, in every live entry point and
inside both USB backends. The policy descriptor records
`read_only_preflight_diagnostic_authorized: true` and
`fixed_proof_hardware_test_authorized: false`; the source audit requires each
gate to be exactly one constant assignment in exactly this state; the
hardware JSON and facts checker carry the same authorization block.

Pins in this revision: policy `130095e976043e1ae93fd9b587d021aa35e5735eba2054267b1fcbbc03d29240`,
executor descriptor `aa9abc64e33df353aad585231c8abfd55eda6ef176d10e0188cbff042ab3caf6`,
executor source `f59ca0b0dd2786ea739f0a7dcf56eae88917725400ce94a0d07f229422492916`.

## What the preflight does

`kb7-loader-reentry-executor.py preflight --commit` opens `10f5:5037` with
the read-only transport (no clear-halt, strict close), takes two complete
32 MiB reads through the loader, requires them identical to each other,
requires the region below the post-image live region (`0x0156b000`)
byte-exact against the reviewed baseline, records the live region's hash,
verifies the loader identity and writes journal boundary 0. It sends no
program or erase command. Its exit codes and stop rules are those of the
[region-1 runbook](REGION1-REENTRY-RUNBOOK-2026-09-05.md).

## What a pass permits

Only preparation and separate review of a mutation-enabled revision that
flips `LIVE_PROOF_CAMPAIGN_ENABLED` for the same campaign identity. A
journal from this revision is bound to this executor source hash and is not
accepted by any other revision.
