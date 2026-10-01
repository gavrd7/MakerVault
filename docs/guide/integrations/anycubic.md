# Anycubic LAN monitoring and ACE

**Optional · Local-first · Experimental / community validation required**

MakerVault can monitor recent Anycubic printers that expose the signed LAN-mode protocol used by the Kobra 3 / S1 generation. No Anycubic Cloud account is required.

## What MakerVault reads

The adapter performs the printer's local handshake over HTTP on port 18910 and then opens the temporary MQTT/TLS session returned by the printer, normally on port 9883.

Where the firmware reports the data, MakerVault can display:

- printer and job state
- current filename
- print progress
- elapsed and remaining time
- current and total layers
- nozzle, bed and chamber temperatures
- local camera-stream availability
- fan/speed metadata
- ACE / ACE Pro boxes and material slots
- material type, colour and remaining percentage
- active ACE slot
- ACE temperature/humidity and drying state when the firmware reports them

The adapter is read-only in v0.7.3. MakerVault sends only the signed local handshake and read/query messages; it does not expose print, movement, heating, drying or other control commands.

## Before you start

1. Put the printer into **LAN mode**.
2. Record its local IP/hostname in the MakerVault owned-printer record.
3. Make sure the MakerVault Docker host can reach the printer on port 18910 and the local MQTT broker returned by the handshake (normally port 9883).

The printer supplies temporary MQTT credentials during the local handshake, so no Anycubic Cloud credentials are stored in MakerVault.

## Add the live source

1. Open **3D Printing** and edit the owned Anycubic printer.
2. Enter its local host/IP.
3. Open **Live monitor**.
4. Choose **Anycubic LAN**.
5. Add the source and choose **Refresh**.

If an ACE unit reports material slots, MakerVault maps them into the provider-neutral `Anycubic ACE / ACE Pro` slot model. MakerVault does not create physical spool inventory automatically from those observations.

## Compatibility

The current implementation targets the signed LAN handshake validated on Kobra 3 / S1-generation firmware. Older Kobra generations may use a different protocol and are deliberately not claimed as supported by this adapter.

The protocol is reverse-engineered rather than a manufacturer-supported public API, so firmware changes may require adapter updates. Keep the integration marked experimental until the relevant model/firmware combination has been exercised against real hardware.
