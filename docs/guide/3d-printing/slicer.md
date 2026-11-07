# MakerVault Slicer: installation and engine management

> **Development status — PR #171:** The optional slicer is not yet released. The final multi-engine installer and approved container image do not exist yet. This guide describes the intended installation and the current limitations. Do not install an unverified engine merely to remove the “No slicer installed” warning.

[MakerVault installation](../getting-started/install.md) · [Technical verification and developer setup](https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/development/self-hosted-slicer.md) · [Slicer roadmap](https://github.com/gavrd7/MakerVault/issues/156)

## Do I need the slicer?

No. Printer integrations, models, G-code files, print history and G-code submission work without it. MakerVault will disable the **MakerVault Slicer** navigation entry and show guidance in **3D Printing** when no verified worker is available.

## Planned one-container installation

The finished version will have **one optional slicing-service container**, under a clearly labelled and initially commented-out section in the standard `compose.yaml`. Uncommenting that service and configuring its required settings will be an administrator choice. Normal installations will not start or download slicer containers. No separate Compose overlays or profiles will be needed.

The normal command remains:

```sh
docker compose config --quiet
docker compose up -d
```

**Not yet actionable:** The current canonical Compose file does not contain the completed optional service, and no approved production multi-engine image is published. The existing `compose.slicer.yaml` is a development-only experimental single-engine overlay, **not** the finished installation method.

## Installing engines individually (planned)

The single slicing-service container will support independently selected engine installations and exact versions. **OrcaSlicer is not required**: a user may install only Creality Print, or any other individually supported verified engine, without installing the others. Each engine has its own native printer, filament and process profiles.

The planned administrator workflow is to select an engine and supported pinned version, review its source/licence/integrity information, explicitly install it, then import or select and verify that engine's native presets. A service may contain several engines, but a slice is routed only to the requested installed and approved engine/version.

**Current PR limitations:** PR #171 now has separate OrcaSlicer and Creality Print worker adapters, an independently verified shared-worker engine registry, official K1/K2 profile discovery for both engines, basic GUI native-profile customisation, and saved slicing drafts. It still lacks a production-ready engine installer, independently verified Linux engine binaries, complete GUI setting coverage, multi-object execution and a successful end-to-end real slicing fixture for either engine. Engine identity verification does not by itself prove that slicing works.

## Profile defaults and spool-aware suggestions (development)

Within **Profile management → Manage profiles** or **Saved profiles**, choose **Set as default** for an imported printer, filament or process profile. Defaults are scoped to your account and that exact slicer engine/version. The official-profile search also offers **Import & set default**; imported profiles remain unverified until tested.

The workbench prefers compatible defaults, then the most recent selection used for the same printer. For a process profile it can suggest an already imported **0.20 mm** standard preset when available. Choosing another printer refreshes its native selections, and the printer's recorded nozzle size is used initially. Use **Restore suggested profiles** to discard manual picks and apply the matching recommendations again.

Selecting a physical spool such as PETG filters suggested native filament profiles and offers to review the official catalogue's matching candidates. This is **not an automatic download or approval**: the user chooses what to import. The physical spool's recorded hex colour is used for the visual build plate unless an object's colour was manually changed.

Both OrcaSlicer and Creality Print machine profiles can provide build plate dimensions for the visual preview. Preview geometry does not certify that a plate is printable; native inheritance, exclusions, physical printer compatibility and real slicing still require independent validation.

## Updating, removing and rolling back engines (planned)

Updates must be initiated by an administrator for the **specific engine**. Other installed engines must remain untouched. Downloaded binaries will need approved version metadata, licence validation, cryptographic integrity checks and tested slicing receipts before activation. Profiles are engine- and version-specific; do not silently convert them.

Removing one engine must preserve other engines and existing MakerVault models/G-code. Pending jobs will require an explicit resolution, and existing approved engine versions should remain available for rollback until the new version has passed verification. Persistent engine/profile storage will survive routine container replacement. Specific storage, backup, removal and rollback commands will be documented when implementation and tests are complete.

## Status messages and troubleshooting

| Status | Meaning |
| --- | --- |
| **No slicer installed or enabled** | The optional slicing deployment has not been enabled. It is safe to leave it this way. |
| **Slicer service unavailable** | Execution was enabled, but no healthy, approved worker was verified. Check the worker container, credentials, image/binary identity and engine approval. |
| **Could not check slicer availability** | The application could not confirm worker status. Check the app connection and logs. |
| **Slicer enabled** | At least one approved worker passed health/identity checks. Specific jobs still require a supported installed engine and verified native profiles. |

Until a verified slicer worker is available, the navigation and Open Slicer button will remain disabled, while 3D Printing and G-code functionality remain available.

## Experimental developer validation

See the [technical slicer guide](https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/development/self-hosted-slicer.md) for the temporary isolated-worker overlay, pinned-image and executable checks, fixture receipts and approval procedures. Its existence does not imply that a complete real OrcaSlicer/Creality Print integration has passed verification. Slicing never automatically starts a print or deducts filament.
