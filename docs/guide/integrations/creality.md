# Creality CFS

**Optional · Read-only local integration**

This adapter reads CFS boxes and loaded filament slots from compatible configured Creality printers. It does not make every Creality printer or multi-material product compatible.

## Set up

1. Add your owned printer in **3D Printing** using the correct model.
2. Open **Manage printer** and confirm that CFS hardware is actually installed, not merely supported by the model.
3. Enter the printer's reachable local host/IP and save.
4. Open **Settings → 3D Printing**, enable Creality CFS and save.
5. Choose **Sync now**. Check the integration status and the printer's discovered slots.
6. Enable scheduled sync only after manual sync works.

The summary distinguishes compatible, installed and configured printers. If these counts differ, correct the owned-printer record before troubleshooting the network.

## Identify a detected reel

A slot can report colour/material without identifying which physical reel you own. Choose its **Add to inventory** action, then link an existing unloaded spool or create a new physical spool. Review weight, status and product information before confirming.

This confirmation avoids producing duplicate inventory whenever a printer reports a filament assignment. Moving a reel between slots does not mean you purchased another reel.

## If no slots appear

Confirm that the printer is on, CFS is connected, the IP has not changed, and MakerVault can reach it across your network/VLAN rules. Review the integration error. Support depends on the printer's available local interface and firmware; a printer catalogue entry alone does not establish compatibility.
