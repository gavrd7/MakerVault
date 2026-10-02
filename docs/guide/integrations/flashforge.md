# FlashForge local monitoring and material stations

**Optional · Local-first · Experimental / community validation required**

MakerVault can monitor recent FlashForge printers that expose the local HTTP API used by the Adventurer 5M / 5M Pro, AD5X and related newer models.

## What MakerVault reads

The adapter polls the local HTTP service on port 8898 using the printer serial number and local check code.

Depending on the printer model and firmware, MakerVault can display:

- printer state
- current print filename
- progress
- elapsed and estimated remaining time
- current and total layers
- nozzle and bed temperatures
- chamber temperature where the printer actually has a chamber sensor
- printer/model/firmware metadata
- printer error codes
- camera availability
- material-station slots where the firmware exposes them

The adapter is read-only. MakerVault does not expose FlashForge job control, movement, heater or raw command interfaces.

## Before you start

You need:

- the printer's local IP/hostname
- the printer serial number
- the local FlashForge check code
- network access from MakerVault to TCP port 8898

The check code is stored server-side and is not returned to the browser after saving.

## Add the live source

1. Add/edit the FlashForge printer in **3D Printing**.
2. Enter its local host/IP and serial number.
3. Open **Live monitor**.
4. Choose **FlashForge local**.
5. Enter the local check code.
6. Add the source and choose **Refresh**.

Material-station observations are stored through MakerVault's provider-neutral `FlashForge material station` slots. Existing user-confirmed spool links are retained and MakerVault does not create physical spools automatically.

## Compatibility

FlashForge firmware varies considerably between product generations. This implementation follows the local `/detail` contract observed in the modern 5M/AD5X/Creator 5 community API work and remains experimental until real hardware testing confirms each family.
