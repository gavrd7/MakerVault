# MakerVault Slicer

MakerVault Slicer provides a browser-based preparation, slicing and G-code review workspace in your self-hosted MakerVault installation. **OrcaSlicer, Creality Print and Bambu Studio** are integrated as independently installed native engines. You can choose an engine without changing the printer's manufacturer: a Creality printer, for example, can use a compatible native profile in more than one engine.

The slicer is **optional to deploy**, but it is part of MakerVault's v1.7.0 feature set. Printer inventory, filament and spools, live monitoring, saved G-code and print submission remain available even when the worker is not installed.

For the basic host installation see [Install MakerVault](../getting-started/install.md). This chapter covers slicer setup and everyday use. [Printers and filament](../using/printing.md) and [Models](../using/models.md) cover the related libraries.

## 1. Enable the slicer service

The single `compose.yaml` starts MakerVault, PostgreSQL, Redis and the separate combined slicer container named `makervault-slicer` (Compose service `slicer-worker`) for **four long-running containers**.

The combined slicer container has two isolated processes with different credentials and filesystem permissions:

- The **worker** runs verified slicer binaries and cannot write to the engine store or make outbound connections.
- The **installer** installs or switches an individual approved engine version into persistent storage when explicitly requested by an administrator.

A separate permissions-initialisation helper runs and exits. It is not a fifth permanent container. The application does not require a Docker socket or direct access to printer credentials in the slicer worker.

Before enabling the slicer container:

1. Preserve your existing `.env`, database, media, encryption keys, backups and engine-store volumes. For a first installation, use [the environment guide](../getting-started/environment.md).
2. Configure distinct worker and installer tokens, a **reviewed combined worker image pinned to its immutable digest**, and the native engine identity/checksum values. Only use actual release-approved values.
3. Validate `compose.yaml`, including all required environment settings.
4. Start the slicer container alongside the base services; check that the worker and installer endpoints are healthy before installing an engine.

```bash
sudo docker compose config --quiet
sudo docker compose up -d
sudo docker compose ps
```

**Important:** The slicer profile requires a *real published/reviewed* combined worker image and verified engine identities; it cannot be deployed securely with placeholder tokens or example checksums. The old standalone staging and production Compose overlays have been retired; existing staging operators must review their private settings and volumes before switching to this one-file deployment. If these assets are not published for the target release, completing slicer setup is blocked rather than safe to guess.

## 2. Install an engine

Open **MakerVault Slicer** and select **View engine installations** (or its equivalent engine-management action). Administrators can review installed and available versions, choose an engine and request an explicit **Install**, **Update**, **Switch** to an approved installed version, or **Uninstall**.

| Engine | Native integration in v1.7.0 |
| --- | --- |
| **OrcaSlicer** | Integrated native slicing, profile import/search, materials and supported painting functions |
| **Creality Print** | Integrated native slicing, Creality profiles and supported multi-material/painting functions |
| **Bambu Studio** | Integrated native slicing, native profile catalogues, multi-colour assignments and validated painting functions |

Availability depends on the exact approved engine binary and version being installed and verified on your host. For example, the Bambu Studio integration has native-binary regression coverage for version **02.09.01.70**. Do not treat future versions or every manufacturer preset as automatically compatible.

Engines and their saved printer/process/filament profiles are separate. Uninstalling one engine must not delete another engine, models or previously saved G-code. Reverting to an older version requires an approved digest; it is not a silent download of an unrelated upstream binary.

If the interface says the slicer service is unavailable, first check that the combined container is healthy and that the worker/installer credentials and approved engine identities agree. An engine shown in a catalogue is not necessarily installed.

## 3. Select your printer and native profiles

Choose the slicing engine, then choose a printer and its matching **native printer, process and filament profiles**. Use **Change printer/profile** to search or import official profiles; the profile search and build-plate selection are available within the common slicer workflow.

- Pick profiles for the **same engine/version**, preserving native inheritance and material requirements. Presets are not interchangeable between Orca, Creality and Bambu simply because they share a printer model name.
- Choose a compatible build plate, nozzle size and printer volume. Bed dimensions or catalogue availability do not prove firmware-level print compatibility.
- Select the filament profiles for every material you intend to use. The associated MakerVault spool can suggest a material and display colour, but selecting a spool does not physically load it or automatically consume its stock.
- Use saved or custom process settings where supported; inspect the resulting G-code when moving between printer or firmware profiles.

A network connection to the printer is **not** required merely to slice and save G-code.

## 4. Prepare a build plate

Add STL/3MF files from the Model Library or by uploading them. In the shared preparation workspace, inspect their arrangement and available scale, rotate, move and per-object settings. Use the object tree to select the model or part you want to edit.

Depending on the engine, native process profiles and nozzle topology, the available controls include:

- Global and per-object print settings, supports, seams and fuzzy skin.
- Material/colour assignment and compatible painting tools.
- Support enforcer/blocker painting, seam painting and fuzzy-skin regions.
- Variable-layer-height editing.
- Multi-material flush-volume and prime-tower settings.

These tools are not universal guarantees. A one-nozzle filament changer has different constraints from a true multi-extruder printer; missing profile data or native binary limitations can cause a request to be rejected. MakerVault checks selected native output where feasible rather than silently claiming unsupported paint or variable-height settings worked.

For Bambu Studio, real binary tests verified two-material output for distinct objects and a facet-painted model, real support-enforcer extrusion on an overhang, seam/fuzzy effects, directional flush-multiplier changes and prime-tower X placement. Variable-layer verification covered requested **0.10 mm / 0.15 mm** bands; an unsupported **0.30 mm** request was rejected after the native binary failed to honour it. This is validation of defined fixtures, **not a guarantee of successful real-world printing**.

## 5. Slice, review and save G-code

Use the slicer's **Slice** action to produce G-code. Wait for the result and inspect the preview, output and available print metadata. The G-code viewer displays supported estimated duration, filament usage and nozzle/bed temperature information extracted from executable commands or labelled profile comments where appropriate.

Check the printer identity, model position, materials/tools, layers, support paths, purge or prime-tower activity and start/end commands before sending anything to a printer. When metadata is absent, a preview cannot invent it; it also cannot fully simulate firmware behaviour.

You can save output to MakerVault's private **G-code Library**, review saved slice jobs and maintain your project/model assets. Slicing alone does **not** submit a job, start a printer, write the printer's material database or deduct physical filament.

## 6. Open the printer monitor and submit a print

The **Device** button opens the selected printer's existing live-monitor modal **over the slicer**. Closing it returns to the current slicer workspace without discarding your build-plate selections.

Printing is a separate, explicit workflow. Where a printer adapter and the selected G-code are compatible, choose a supported upload or print-start action, review the target printer and material/tool mapping, then confirm. The existing printer submission guards and telemetry checks still apply. Some adapters are monitoring-only, and proprietary multi-material commands may require additional physical validation.

See [printer controls](../integrations/printer-controls.md) and [printer compatibility](../integrations/printer-adapter-validation.md).

## 7. Update or remove engines safely

Use the administrator's engine manager for individual engine lifecycle actions. Normal MakerVault application updates are **not** permission to replace every native slicer binary.

For application updates, retain the persistent engine volume. Read [Update MakerVault](../administration/updates.md). Never use `docker compose down -v`: it can remove database, media, encryption key and installed engine storage.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| **MakerVault Slicer unavailable** | Worker health, Compose overlay, service DNS, separate credentials and published image identity |
| **No engines shown as installed** | Installer health, persistent engine-store permissions and approved engine versions |
| **Profiles cannot be selected** | Native profile type, required parent profiles, engine/version and printer/nozzle compatibility |
| **Slice rejected** | Real native capability, model/3MF integrity, assigned material/tool count and process settings |
| **Unexpected colours or purge** | Tool mapping, flush volumes, tower placement, G-code preview and printer firmware requirements |
| **Device monitor closes to another page** | Refresh to a version including the in-place Device modal fix; the monitor should no longer navigate away |

For a release install or upgrade, record the exact engine/version and non-sensitive diagnostic logs. Do not share secrets or unredacted full `.env` files.

## Further guidance

- [Getting started and Docker installation](../getting-started/install.md)
- [Environment configuration](../getting-started/environment.md)
- [Models and revisions](../using/models.md)
- [Printers, filament and spools](../using/printing.md)
- [Upgrade and backup](../administration/updates.md)
