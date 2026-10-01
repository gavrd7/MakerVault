# Printer adapter validation

MakerVault deliberately separates **implemented** from **hardware validated**. Manufacturer-local protocols can vary between models and firmware, so adapters that have not been exercised on real hardware remain marked **Community validation required**.

## Before testing

Use a normal owned-printer record with the correct manufacturer/model, serial number where required, and a reachable local hostname/IP.

Do not share:

- Bambu LAN access codes
- FlashForge check codes
- PrusaLink passwords or API keys
- any reverse-proxy or service credentials

MakerVault keeps these values server-side and excludes them from the Live monitor diagnostics export.

## Repeatable validation checklist

For each printer/firmware combination:

1. Add the recommended live source in **3D Printing → Live monitor**.
2. Confirm the adapter's compatibility note matches that model.
3. Choose **Refresh** while the printer is idle.
4. Verify state and temperatures are plausible.
5. If the printer has a material system, compare every reported slot with the physical unit.
6. Start a small ordinary test print.
7. Confirm filename, progress, elapsed/remaining time and layer counters where the adapter supports them.
8. Pause/resume from the printer itself and check that MakerVault observes the state change. For sources with [optional controls](printer-controls.md), separately test the disabled-by-default opt-in, Pause, Resume and confirmed Cancel on a small print.
9. Let the print finish or cancel it from the printer and confirm Print History records the correct terminal state.
10. Return to idle and confirm MakerVault does not invent a second PrintJob.
11. Use **Copy diagnostics** from the live-source card and review the JSON before sharing it with the MakerVault maintainer.

## Useful report details

A good validation report includes:

- manufacturer and exact model
- firmware version
- MakerVault commit/version
- adapter selected
- idle/printing/paused/completed states observed
- which temperature fields were correct
- whether filename, progress, time and layers matched the printer
- multi-material system and slot count
- any missing or incorrect fields
- the sanitized **Copy diagnostics** output

Diagnostics may contain the printer model/serial and active print filename, so review those fields before sharing.

## Current validation state

- **Creality local:** hardware validated against the development Creality K2; other firmware/models remain experimental.
- **Moonraker / Klipper:** protocol implementation is established; manufacturer profiles still need representative model testing.
- **OctoPrint:** established API implementation.
- **Bambu Lab local:** fixture/contract tested; community hardware validation required.
- **PrusaLink:** fixture/contract tested; community hardware validation required.
- **Anycubic LAN:** fixture/contract tested for Kobra 3/S1-generation LAN semantics; community hardware validation required.
- **FlashForge local:** fixture/contract tested for newer local port-8898 semantics; community hardware validation required.
- **Elegoo/QIDI/Sovol/Snapmaker U1/Voron profiles:** reuse Moonraker and require representative manufacturer firmware validation.

An adapter should only lose its experimental/community-validation label after successful real-hardware testing on representative firmware.

Hardware testing still to do is tracked in [TODO #37](https://github.com/gavrd7/MakerVault/issues/37). K2 monitoring confirmation does not validate the new control commands. Validate control behaviour separately and record failures or firmware differences before promoting that capability.
