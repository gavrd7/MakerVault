# MakerVault Slicer: installation and engine management

> **Development status — PR #171:** The optional slicer is not yet released. The final multi-engine installer and approved container image do not exist yet. This guide describes the intended installation and the current limitations. Do not install an unverified engine merely to remove the “No slicer installed” warning.

[MakerVault installation](../getting-started/install.md) · [Technical verification and developer setup](https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/development/self-hosted-slicer.md) · [Slicer roadmap](https://github.com/gavrd7/MakerVault/issues/156)

## Do I need the slicer?

No. Printer integrations, models, G-code files, print history and G-code submission work without it. MakerVault will disable the **MakerVault Slicer** navigation entry and show guidance in **3D Printing** when no verified worker is available.

## Adding the slicer container to an existing installation

**An existing MakerVault installation does not need to be reinstalled, reset or given Docker privileges.** The optional slicer service is a separate container on the same private Compose network. The host administrator needs Docker access **once** to add the service; MakerVault's web application itself must not receive the Docker socket or privileged mode. The normal app, database, Redis, printer connections and existing storage volumes remain in place.

### Existing staging installation — available now for experimental testing

For an existing **Debian x86_64 staging** checkout of PR #171, use the explicitly invoked OrcaSlicer staging installer. It stages the binary, creates a private configuration file, builds the optional worker and adds the worker using a Compose overlay. Back up your MakerVault data before testing and confirm there is adequate disk space for the extra image.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation

# Download and checksum-verify the upstream OrcaSlicer release;
# build the optional local worker image.
sudo python3 scripts/install_slicer_staging.py prepare-orca

# Add and start the isolated worker alongside the existing app.
sudo python3 scripts/install_slicer_staging.py enable

# Confirm the worker is present; this alone does NOT prove slicing works.
sudo python3 scripts/install_slicer_staging.py status
```

Once the service is running, return to **MakerVault Slicer → View engine installations**. Import compatible native printer, filament and process profiles for OrcaSlicer. An administrator must run **Test slice and approve** with real G-code output before the engine/profile combination can be used for ordinary slicing. The present staging installer does **not** yet install or update engines from a browser.

**For routine staging updates once the slicer worker has been installed**, retain the slicer overlay and both environment files. Otherwise a normal three-file Compose update may remove the app's worker connection settings:

```bash
cd ~/MakerVault-Staging
sudo python3 scripts/install_slicer_staging.py enable
```

To switch the slicer service off without touching the rest of MakerVault:

```bash
cd ~/MakerVault-Staging
sudo python3 scripts/install_slicer_staging.py disable
```

Do **not** use `docker compose down -v` or delete existing MakerVault named volumes. Do not commit, publish or share `.slicer-staging.env`: it contains the private worker access token. If the staging installation uses a custom Compose layout, inspect the generated configuration before enabling the service.

### Existing production installation — planned workflow

The stable production image and browser-based engine manager are **not yet released**, so the staging commands above are not production installation instructions. The intended production sequence is: update MakerVault normally without replacing its existing volumes; enable the one optional slicer-service container in the supported Compose configuration; start **only that additional service**; then install, update or uninstall individual supported slicer engines through the MakerVault administrator UI.

Once the optional container is deployed, normal engine management should require neither redeploying MakerVault nor giving the web container host-level privileges. Engine binaries will live in a separate persistent volume and the management API will be scoped to that service. There is no requirement to stop, reinstall or reset an existing MakerVault database to add the slicer.

## Install OrcaSlicer on a separate staging server (experimental)

For developers testing PR #171 on Debian x86_64, there is now an **explicit opt-in staging installer**. It retrieves OrcaSlicer 2.4.2 from the official GitHub release, verifies the release asset's SHA-256, builds a locally pinned isolated Docker worker and enables worker connectivity for the staging app. It does **not** install or enable Creality Print.

```bash
cd ~/MakerVault-Staging
git pull --ff-only origin feature/self-hosted-slicer-foundation
sudo python3 scripts/install_slicer_staging.py prepare-orca
sudo python3 scripts/install_slicer_staging.py enable
sudo python3 scripts/install_slicer_staging.py status
```

After installation, choose the Orca engine in MakerVault, import matching native printer/filament/process presets and use **Test slice and approve** (administrator only) to validate that actual slicing produces G-code. Only then can the normal **Save and slice** action succeed. This is deliberately a staging experiment: the official OrcaSlicer 2.4.2 image has passed real K1 fixture slicing, with the K2 only passing a clearly identified test-only profile workaround. Neither receipt automatically approves a user's native profiles or printer.

The optional staging configuration is held in a private `.slicer-staging.env`. Existing MakerVault storage is untouched. To turn engine execution back off:

```bash
sudo python3 scripts/install_slicer_staging.py disable
```

For subsequent staging updates, repeat the installer's **enable** command rather than the old three-Compose-file update alone; the installer adds the additional optional service automatically. Do not use this on production. A fully browser-operated engine installer is still planned.

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

**Current PR limitations:** PR #171 now has separate OrcaSlicer and Creality Print worker adapters, an independently verified shared-worker engine registry, official Orca profile discovery across pinned upstream vendor catalogues (with Creality-only native discovery for Creality Print), basic GUI native-profile customisation, and saved slicing drafts. It still lacks a production-ready engine installer, independently verified Linux engine binaries, complete GUI setting coverage, multi-object execution and a successful end-to-end real slicing fixture for either engine. Engine identity verification does not by itself prove that slicing works.

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

See the [technical slicer guide](https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/development/self-hosted-slicer.md) for the temporary isolated-worker overlay, pinned-image and executable checks, fixture receipts and approval procedures. Its existence does not imply that a complete multi-engine, multi-printer slicing workflow has passed verification. Slicing never automatically starts a print or deducts filament.

## Using a different printer or a custom machine profile

OrcaSlicer v2.4.2's pinned official catalogue browser now exposes its upstream manufacturer families (including Prusa, Voron, Anycubic, Elegoo, Qidi and Custom), rather than requiring a Creality printer. Choose **MakerVault Slicer → Search official profiles → OrcaSlicer**, select the manufacturer/catalogue, then search printer, filament and process profiles separately. These are **upstream catalogue sources**, not a guarantee that every machine is supported or that the chosen preset can be used safely. The Creality Print catalogue remains Creality-specific.

If a printer is not listed, use **Import native profile** with a profile supported by the chosen engine/version. Imported vendor or custom profiles remain candidates until the operator approves a successful, reviewed slicing fixture. Firmware-specific G-code, nozzle/extruder capabilities and geometry must match the actual printer. A printer does **not** need a network upload adapter merely to slice and save G-code; sending and starting a print is a separate action.

Native parent profiles are only imported when their relationships are verifiable in the pinned source catalogue. If two manufacturers use the same native parent name with different contents, MakerVault refuses the conflicting import rather than silently mixing their printer settings. This cross-vendor namespace limitation remains a development item.
