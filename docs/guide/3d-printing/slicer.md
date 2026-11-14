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

Once the service is running, return to **MakerVault Slicer → View engine installations**. Import compatible native printer, filament and process profiles for OrcaSlicer. Imported native profiles are checked for ownership, intact content and complete parent dependencies when slicing; manual administrator approval is not required. The present staging installer does **not** yet install or update engines from a browser.

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

After installation, choose the Orca engine in MakerVault and import matching native printer/filament/process presets. From **Slicer setup**, use **Quick slice** to generate private G-code directly, or **Slice** to open the interactive editor and then generate and preview G-code. Library saving and printer upload/start are explicit actions in the interactive slicing result. Imported profiles are validated automatically on each slicing request. This is deliberately a staging experiment: the official OrcaSlicer 2.4.2 image has passed real K1 fixture slicing, with the K2 only passing a clearly identified test-only profile workaround. Engine tests do not guarantee a particular printer/profile combination will produce correct G-code; inspect the result before printing.

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

**Current PR limitations:** PR #171 includes OrcaSlicer and Creality Print worker adapters, a separately installed, pinned and isolated engine worker, upstream multi-manufacturer profile browsing, native-profile customisation, saved slice drafts, G-code output and a visual build plate. **The real OrcaSlicer 2.4.2 binary has passed single-STL fixtures for K1, a test-only-adjusted K2, and Prusa MK4, plus a two-model, single-filament compound 3MF fixture built by MakerVault.** Actual staging end-to-end profile approval and G-code review still require operator testing. There is no verified native multi-extruder/CFS print workflow, full GUI setting parity or production-ready multi-engine installer. Creality Print and the other engines are not yet real-CLI approved.

### Planned slicer engine coverage

The long-term goal is a single MakerVault interface with independently installable
slicing engines: **OrcaSlicer**, **Creality Print**, **Bambu Studio**,
**PrusaSlicer**, **Snapmaker Orca**, **ElegooSlicer**, **UltiMaker Cura**
(with a separately tested CuraEngine backend), and **Anycubic Slicer Next**.
Other manufacturer engines may follow once their executable, native profiles,
licensing, and output pass isolated acceptance testing. ElegooSlicer,
UltiMaker Cura and Anycubic Slicer Next are currently
**roadmap candidates, not working integrations**. Listing an engine does not
make it installable, verified, or ready to slice.

MakerVault's common build-plate and print-submission workflow should work
consistently across engines where their native capabilities allow it, while
preserving each engine's distinct profile formats, version requirements and
multi-material semantics. A printer's brand does not force the user to choose
that manufacturer's slicer.

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
| **Slicer enabled** | At least one approved worker passed health/identity checks. Specific jobs still require a supported engine and valid owner-scoped native profiles. |

Until a verified slicer worker is available, the navigation and Open Slicer button will remain disabled, while 3D Printing and G-code functionality remain available.

## Experimental developer validation

See the [technical slicer guide](https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/development/self-hosted-slicer.md) for the temporary isolated-worker overlay, pinned-image and executable checks, fixture receipts and approval procedures. Its existence does not imply that a complete multi-engine, multi-printer slicing workflow has passed verification. Slicing never automatically starts a print or deducts filament.

## Using a different printer or a custom machine profile

OrcaSlicer v2.4.2's pinned official catalogue browser now exposes its upstream manufacturer families (including Prusa, Voron, Anycubic, Elegoo, Qidi and Custom), rather than requiring a Creality printer. Choose **MakerVault Slicer → Search official profiles → OrcaSlicer**, select the manufacturer/catalogue, then search printer, filament and process profiles separately. These are **upstream catalogue sources**, not a guarantee that every machine is supported or that the chosen preset can be used safely. Creality Print 7.3.0 also has its own pinned upstream manufacturer catalogues (including Prusa, Voron, Anycubic and Custom); its profiles remain distinct from OrcaSlicer profiles even for the same printer.

If a printer is not listed, use **Import native profile** with a profile supported by the chosen engine/version. Imported vendor and custom profiles are checked for content integrity and parent dependencies at slice time; operator fixture approval is optional. Firmware-specific G-code, nozzle/extruder capabilities and geometry must match the actual printer. A printer does **not** need a network upload adapter merely to slice and save G-code; sending and starting a print is a separate action.

Native parent profiles are only imported when their relationships are verifiable in the pinned source catalogue. If two manufacturers use the same native parent name with different contents, MakerVault refuses the conflicting import rather than silently mixing their printer settings. This cross-vendor namespace limitation remains a development item.

## Cross-manufacturer profiles in every slicing engine

MakerVault's slicer selection is **not restricted by printer brand**. The selected engine determines the native profile format, available upstream profile sources, slicing options and version-specific acceptance tests. Profiles are **not interchangeable across engines**: even when two slicers provide a preset for the same machine, each preset must retain its own engine/version, upstream provenance, inheritance and independent validation.

The shared profile-source endpoint reports catalogue availability for every listed engine. **OrcaSlicer v2.4.2** currently browses 65 pinned upstream profile families; **Creality Print v7.3.0** currently browses 36 pinned profile families. These counts refer to source catalogues, not tested printer models. The other catalogue engine entries currently support **manual native-profile registration as unverified candidates**; their official browsers and engine runtimes are not yet validated or enabled for slicing. No missing catalogue is silently substituted with an OrcaSlicer/Creality Print preset.

For engines without a searchable catalogue, choose **Import native profile file instead** and use the exact engine-native format. Slicing requires a healthy isolated worker and valid, complete native profiles. Profiles may be configured for offline slicing without enabling printer-network control, which is handled separately by printer adapters.

## Slicing multiple STL models with OrcaSlicer

The visual build plate saves individual model files, positions, scale, rotation
and preview colours as draft data. With a healthy pinned OrcaSlicer worker
and intact native printer, filament and process profiles, MakerVault can
prepare a **single-material** multi-STL slice. The
worker input is a bounded compound 3MF which combines the models' transformed
geometry into separate islands inside one mesh. This is intentional: the
official OrcaSlicer 2.4.2 command-line executable was demonstrated to slice
only one of multiple independent build objects from a minimal core 3MF, while
the compound-geometry route passed a real two-island extrusion fixture test.

The combined slice uses **one native filament profile for all imported models**.
Individual model preview colours do not yet select physical extruders or CFS
slots. Separate native materials, tool-changing, multiple build plates,
firmware-specific commands and physical printer behaviour still need explicit
engine- and printer-specific validation. Non-Orca multi-STL slice execution
remains disabled until separately verified. A successful slice stores G-code
for review; it does **not** send or start printing or deduct filament stock.

### Save draft, Quick slice and Slice

The actions appear together below the setup build plate. **Save draft** retains the configuration and models without running an engine. **Quick slice** immediately queues a slice using the selected profiles; its output remains private and opens a read-only preview without direct library or printer actions. **Slice** opens the full interactive Prepare workspace, including when no model has yet been imported. There, **Save draft** and **Slice and preview** are available; completed interactive slices provide explicit **Add G-code to library**, **Upload to printer**, and **Upload and start print** actions. No slicing action itself starts a printer or deducts inventory.

The checkbox **Also save imported models to MakerVault Files** is optional. If left unchecked, the source STL is stored privately for the slicing job and saved draft, not in the standard Files or model library. Such private inputs remain accessible when editing the draft and are removed when their last referencing draft is deleted. Disk quota and upload limits still apply.

## Interactive slicer — initial Prepare workspace

After choosing an engine, printer and profiles in **Slicer setup**, select **Slice** at the bottom to open the full interactive workspace. You can add STL models before or after entering the editor. This opens a separate Prepare workspace while retaining the previously configured native profiles.

The initial workspace includes an object tree (instances on the first plate), click-to-select, active **Move**, **Rotate**, **Scale**, **Auto-arrange**, **Duplicate** and **Remove** controls backed by the existing 3D plate editor, and in-session undo/redo (Ctrl+Z / Ctrl+Y outside text inputs). **Save draft** and **Slice and preview** share the existing isolated worker submission path with Quick slice, while explicit G-code saving and printer submission happen from the completed interactive result. Reopening an unscheduled draft returns to the interactive editor with the saved build plate.

The categories **Quality**, **Strength**, **Speed**, **Supports**, **Multifilament**, and **Others** organise the Prepare settings. With an imported OrcaSlicer native process preset selected, **Global** exposes the recognised numeric process fields actually present in the resolved native profile. Edits are validated, saved with the draft, and applied only to the worker's temporary copy of the native process profile. **Restore profile defaults** discards those per-draft overrides. Printer start G-code, filament-change commands, printer settings and the original official profile are never altered. The interactive **Print settings** panel now has a process-profile dropdown above
the Global/Object controls. It lists registered process presets for the selected
slicer engine **and exact engine version**. Switching presets discards this
draft's temporary edits only after confirmation; **Reset edits** restores the
currently selected preset's values without changing the selected profile.
Manufacturer profiles are never overwritten.

**Basic** is the concise set of everyday settings: layer height, default line
width, wall/shell counts, infill density and pattern, seam position, primary
wall/infill/travel speeds, support enable/angle/build-plate-only and brim/skirt.
**Advanced** includes everything in Basic plus less frequently adjusted
parameters, grouped under their native Orca process headings such as Layer
height, Line width, Seam, Precision, Top/bottom shells, Infill, Acceleration,
Support, Raft, Skirt and Brim. Search works across those headings and categories
at the selected detail level. Only settings which exist in the selected resolved
native profile, have an explicitly supported native data type and pass strict
value validation are editable. Some Orca Expert options (mixed mm/percent
expressions, G-code templates, multi-material purge settings and engine-specific
nested structures) remain intentionally unavailable in this pass. Their current
values remain in the native preset and are not discarded.

After adjusting global process settings, select **Save as custom profile**,
enter a unique name, then **Save and select profile**. MakerVault creates an
independent, flattened OrcaSlicer process preset using the current native
process configuration plus your changed fields. The original manufacturer
profile and its other settings are untouched. The new preset appears in
**Saved profiles** under the same engine/version and becomes the current
session's process selection. The temporary per-draft overrides are cleared
because those values are now part of the saved preset. New custom presets
remain *unverified candidates* until the normal native engine/profile checks
are completed; saving one does not approve it for automatic execution.

The **Object** scope and **Multifilament** settings remain informational until native per-model materials and tool changes can be validated. Other engines can still use their native profile editors while per-draft setting schemas are expanded. Independent X, Y and Z scaling is available with preview/3MF persistence; each axis is validated between 5% and 400%. Advanced transformations, multi-plate output and painting tools remain disabled.

### G-code Preview controls

Completed slicing jobs open an in-modal read-only G-code preview. The first expanded preview provides slicer-declared material/time estimates, a vertically oriented *sampled layer* control, a horizontal *sampled extrusion step* control, a toolhead marker, and feature visibility checkboxes. Colouring by extrusion line type or sample layer height is available. Options requiring actual feed/temperature/flow/acceleration/filament metadata are disabled, rather than fabricated.

**Important:** This first preview still visualises sampled extrusion segments, not the complete 3D printer motion plan. It may omit layers or moves and cannot be used as a substitute for native OrcaSlicer verification. A complete indexed toolpath including travel, retract/wipe and true native metrics is scheduled as a distinct acceptance milestone.

See the implementation phases in `docs/development/interactive-slicer-plan.md`.


### Automatic official printer artwork

After importing an official printer-model candidate, MakerVault attempts to
resolve and cache vetted native `bed_texture` (SVG) and `bed_model` (STL)
resources via the authenticated application API. Artwork is decorative and
does not alter printing, purging, slicing or printer compatibility. A missing,
unsupported or unsafe asset uses the procedural MakerVault plate. The official
catalogue browser currently covers release-pinned OrcaSlicer, Creality Print
and Snapmaker Orca native presets. Bambu Studio and PrusaSlicer expose
**printer-model artwork metadata only** at this stage; these records are not
sufficient to slice a print. Installation-specific worker profile discovery,
additional engine-version adapters and actual printer-specific artwork
validation are separate milestones. Users may keep using manually imported
profiles and the generic 3D build plate offline.
