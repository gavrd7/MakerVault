# Bambu Lab local monitoring and AMS

**Optional · Local-first · Experimental / community validation required**

MakerVault can monitor compatible Bambu Lab printers directly over the local network without requiring Bambu Cloud.

## What MakerVault reads

The adapter uses the printer's local MQTT/TLS service on port 8883. MakerVault normalises the reported data into the same live-printer model used by Moonraker, OctoPrint and Creality.

Where the printer reports the data, MakerVault can display:

- online/printer state
- current file/job name
- print progress
- elapsed and remaining time
- current and total layers
- nozzle, bed and chamber temperatures
- HMS/error indicators
- AMS units and loaded trays
- filament type, colour and remaining percentage
- AMS tray selection and RFID/tag presence
- camera availability metadata

The integration is read-only in v0.7.3. MakerVault does not expose start print, motion, heating, raw G-code or other high-impact controls.

## Before you start

You need:

- the printer's local IP/hostname
- the printer serial number
- the LAN access code shown by the printer
- local network access from the MakerVault container host to TCP port 8883

The LAN access code is stored server-side and is not returned to the browser after saving.

## Add the live source

1. Add or edit the printer in **3D Printing**.
2. Enter its serial number and local host/IP.
3. Open **Live monitor**.
4. Choose **Bambu Lab local**.
5. Confirm the serial number and enter the LAN access code.
6. Add the source, then choose **Refresh** for the first connection test.

When the adapter connects successfully, the live panel should show printer state and temperatures. If AMS data is reported, MakerVault also creates or updates provider-neutral Bambu Lab AMS slot records on that physical printer.

MakerVault never creates a physical spool merely because an AMS slot reports filament. Existing user-confirmed spool links are preserved; automatic spool creation remains deliberately conservative.

## Security note

Bambu printers expose MQTT over TLS with a device-local certificate rather than a normal public-CA website certificate. MakerVault therefore uses the encrypted local MQTT channel plus the LAN access code, but this adapter cannot provide ordinary public hostname/certificate validation. Keep the printer and MakerVault on a trusted LAN/VLAN.

## Troubleshooting

If MakerVault cannot connect, verify the host/IP, LAN access code and serial number, and make sure port 8883 is reachable from the Docker host. Firmware changes can alter undocumented local behaviour, so Bambu support remains experimental until it has been validated on more real hardware and firmware versions.
