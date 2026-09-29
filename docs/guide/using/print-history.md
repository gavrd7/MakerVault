# Print history and costs

**Goal:** record what was printed, the outcome and the material actually used.

## Record a print

1. In **3D Printing**, open print history and use the print-record action.
2. Choose the owned printer and, where appropriate, model/revision and project.
3. Enter quantity, status and estimated/actual duration as applicable.
4. Add material usage rows for the physical spools used, with used filament and waste.
5. Check material cost/currency, add notes and save.

Use the exact revision printed, not just whichever model file is newest today. Record failed prints too if you want meaningful success-rate and waste information. External history imports should be checked before adding another manual record for the same job.

## How material estimates work

A spool needs an initial filament weight and purchase cost to calculate cost per gram. MakerVault estimates each usage row from:

```text
(used filament + waste) × (spool purchase cost ÷ initial filament weight)
```

Example: a 1,000 g spool costing £20 has a cost of £0.02/g. A print with 30 g used and 5 g waste estimates **£0.70** in material.

Review the shown estimate before saving; you can override it. Stored historical costs remain authoritative after creation. Changing today's spool price should not be interpreted as repricing every earlier print.

These figures represent recorded material cost. They do not automatically include electricity, machine wear, labour, postage or profit. Different currencies are kept separate rather than silently converted or added together.

## Read the overview

The overview summarises recorded print time, material consumed, waste, material cost and per-printer results. Success rates depend on the jobs and statuses recorded; missing or incomplete history makes them incomplete. Duration and usage supplied by a service can also be missing or approximate.

A history entry is not a command to start a printer. Check spool remaining weight after changes or synchronisation; do not assume a manually entered usage figure guarantees live physical weight measurement.
