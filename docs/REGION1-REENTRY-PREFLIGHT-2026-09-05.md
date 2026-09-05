# Region-1 campaign: read-only preflight record, 2026-09-05

Revision: branch `region1-reentry-preflight-only`, executor source
`f59ca0b0…`, campaign `9a582f1c…`, baseline `2b1472f4…`.

Setup: bare board on USB only, SPI pigtails insulated and unconnected,
programmer on the bench, automount masked and stopped for the session,
loader entered with the vendor mode switch (`10f5:5037`, USB address 4).
The executor ran as a transient root service detached from the terminal.

Result: **exit 0**, journal `boundary_verified` at boundary 0 after two
complete 32 MiB reads that were identical to each other and byte-exact
against the baseline below the live region. Observed full-chip image
`35968ec5…`, the same value as the 2026-09-02 and 2026-09-03 captures; live
region `04b21e78…`, unchanged since the 2026-09-03 preflight, so the stock
settings store has not been rewritten since. Loader window `9cc33333…` and
manifest `a945368…` exact. No program or erase command was sent; the
revision cannot send one.

What this permits: preparation and separate review of a mutation-enabled
revision for the same campaign identity. Its journal will be bound to that
revision's executor source, so the campaign session starts with its own
preflight.
