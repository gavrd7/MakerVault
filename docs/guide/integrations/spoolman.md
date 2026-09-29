# Spoolman

**Optional · Administrator/staff setup**

Use this when you already run Spoolman and want to synchronise spool information. MakerVault works without it.

## Connect

1. Open **Settings → 3D Printing** and find Spoolman.
2. Enable the integration and enter the server URL, for example `http://192.168.1.60:7912`.
3. Start with **External → MakerVault** if you want to import existing Spoolman inventory.
4. Choose **Save**, then **Test connection**.
5. Run **Sync now** and inspect the status, resulting spools and any review requests.
6. After the first result is correct, enable **Scheduled sync**, choose an interval and save.

The URL must be reachable from the MakerVault container. `localhost` there refers to MakerVault's own container, not your host or another container. Use a reachable server address or a deliberately configured shared Docker network.

## Choose the direction deliberately

| Direction | Intention |
| --- | --- |
| External → MakerVault | Import from Spoolman |
| MakerVault → external | Export to Spoolman |
| Bidirectional | Synchronise supported data in both directions |

Export and bidirectional modes can change the external service. Back up existing records before using them. They are not a blanket promise that every field is mirrored in both directions.

MakerVault keeps its existing filament identity, placement, notes and status authoritative rather than silently replacing them with remote values. New imports may inherit remote location information. Review the results of the first sync before enabling a recurring schedule.

## Resolve possible duplicates

Choose **Review … possible duplicates** when offered. Compare physical spool identity, weight, product and any RFID/UID. Then choose one action:

- Link the matching existing MakerVault spool.
- Import as a genuinely new spool, using an existing or detected filament product.
- Ignore the remote spool.

Material and colour alone are insufficient evidence that two entries represent the same reel. Ignored imports can be reconsidered using the offered control.

## Connection problems

Check Spoolman's availability, its URL/port and network access from the MakerVault host/container. A working browser connection from your laptop does not prove the container can reach it. Read the last integration error before changing mappings or repeatedly importing.
