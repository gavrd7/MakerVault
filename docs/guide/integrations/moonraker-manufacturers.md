# Moonraker-based manufacturer profiles

**Optional · Local-first · Experimental by manufacturer/model**

MakerVault uses the standard Moonraker adapter wherever a manufacturer exposes a normal Klipper/Moonraker interface. This avoids maintaining duplicate protocol implementations for printers that already speak the same API.

## Current routed profiles

MakerVault currently exposes manufacturer-labelled Moonraker profiles for:

- **Elegoo** — Neptune 4 family and OrangeStorm models that expose stock Moonraker
- **QIDI** — current Klipper-based high-speed models such as Plus4, Q1 Pro, X-Max 3, X-Plus 3, X-Smart 3 and Q2
- **Sovol** — SV08-family printers
- **Snapmaker** — U1, whose firmware is built on Klipper/Moonraker/Fluidd
- **Voron** — community Klipper/Moonraker installations

These profiles use the same normalised live status contract as the generic Moonraker source. A manufacturer profile does not imply that every printer ever sold by that brand uses Moonraker.

## Add a source

1. Add/edit the owned printer and set its local hostname/IP.
2. Open **Live monitor**.
3. MakerVault prefers the matching manufacturer profile only for known Moonraker-based model families.
4. A bare hostname/IP defaults to Moonraker port **7125**.
5. If the printer uses a different port or reverse-proxy route, enter the full HTTP(S) URL instead.
6. Add the source and choose **Refresh**.

Examples:

- `neptune4.local` → `http://neptune4.local:7125`
- `sv08.local` → `http://sv08.local:7125`
- `http://u1.local/moonraker/printer1` keeps the explicit Snapmaker route prefix

## What is monitored

Where the printer's Moonraker build exposes it, MakerVault reads:

- printer/print state
- active filename
- print progress
- elapsed/estimated remaining time
- current/total layer metadata when present
- nozzle and bed temperatures, including additional standard Klipper extruders when reported
- the active nozzle when Klipper identifies it
- Moonraker/Klipper warnings

Monitoring is read-only by default. Per-source opt-in enables Pause, Resume and confirmed Cancel where supported; macros, motion, heating and raw G-code are not exposed. See [optional controls](printer-controls.md). Hardware validation is separate from the shared protocol implementation.

## Model limitations

Manufacturer firmware can pin or modify Moonraker versions. MakerVault therefore treats these profiles as experimental until tested on representative hardware.

In particular:

- Elegoo Centauri models do **not** automatically use the Neptune/OrangeStorm Moonraker profile.
- Older/non-Klipper QIDI and Sovol models should use another source only if they actually expose that protocol.
- Snapmaker 2.0/A-series models are not treated as U1 Moonraker printers merely because the manufacturer is Snapmaker.

If a model is not automatically preferred, the generic **Moonraker / Klipper** source remains available for users who know their printer exposes it.

## Multiple nozzles

MakerVault discovers standard `extruder`, `extruder1`, `extruder2` and subsequent numbered heaters from Klipper's `heaters.available_heaters` response. Live cards show each reported nozzle separately and mark the active nozzle from `toolhead.extruder`. Tool numbering is preserved even when an intermediate tool is absent. Custom-named tool systems are not inferred.

This extends the shared adapter for compatible Snapmaker, Voron and other multi-extruder installations. It does not create material slots or infer which physical spool is loaded. Manufacturer/model support remains experimental until hardware validation.

If additional nozzle readings temporarily fail, the main print status and first-nozzle/bed readings remain available with a warning.

Protocol references: [Moonraker object queries](https://moonraker.readthedocs.io/en/latest/external_api/printer/#query-printer-object-status) and [Klipper status fields](https://www.klipper3d.org/Status_Reference.html#heaters).

