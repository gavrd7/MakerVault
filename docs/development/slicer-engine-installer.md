# In-browser slicer engine installation — staging foundation

MakerVault's browser uses one shared isolated slicer worker for all engines.
The optional `slicer-engine-installer` service is a separate container with
**write** access only to the versioned slicer-engine Docker volume. The worker
has **read-only** access to that same volume. No Docker socket, host shell,
printer access, media folder or database credentials are mounted into the installer.

## First enablement on existing staging

After updating the app and retaining the functioning OrcaSlicer environment:

```sh
cd ~/MakerVault-Staging
git pull --ff-only origin main
sudo python3 scripts/install_slicer_staging.py update
sudo python3 scripts/install_slicer_staging.py enable-engine-installer
```

The second command is needed **once**. It creates a private installer token in
`.slicer-staging.env`, rebuilds the isolated worker wrapper to understand the
shared engine store, imports the **existing staging Orca** binary with its
recorded checksum, builds the restricted installer and links MakerVault to it.

No existing slicing job is started by this command. An already-sliced G-code
file is unchanged. Previous Orca version data are kept.

Subsequent app updates use the normal `update` command. Engine downloads and
upgrades are initiated by users in **Slicer setup → View engine installations**.

## Engine installation and version management

The installer discovers **Creality Print** releases through the official
`CrealityOfficial/CrealityPrint` GitHub releases API, checking each Linux
x86-64 AppImage against its published SHA-256. **OrcaSlicer** offers the reviewed MakerVault K2-compatible source build 2.5.0 (when its binary prerelease is published), plus separately pinned upstream version 2.4.2 for unvalidated older-version selection. This includes
earlier versions, not just updates newer than the current installation.

A single version dropdown on each engine card lists the current version,
other locally installed versions and verified downloadable versions. Selecting
an earlier **local** version switches the active engine only after checking
its saved executable identity and SHA-256; selecting an **uninstalled**
version downloads and verifies the pinned official AppImage before activating.
When the selected version is already current, no redundant Installed button
is shown. Release metadata is cached for ten minutes. Direct user-provided
download URLs, commands and filesystem paths are not accepted.

1. The user chooses an available version and clicks **Install**.
2. MakerVault sends an authenticated request to the installer (internal network only).
3. The installer downloads official bytes with bounded redirects and size,
   compares the final SHA-256 against the official release metadata and
   extracts the AppImage inside its restricted container.
4. It attempts a fixed, bounded headless CLI compatibility check (`--help` for Orca, `--cli --help` for Creality).
5. Only a successful smoke check permits atomic activation. Older engine
   directories and the previous active selection remain available for rollback.
6. MakerVault polls installation status. The worker independently checks the
   extracted executable SHA-256 against the manifest before showing an engine
   as installed.

**Important limitation:** `--help` is a packaging/CLI smoke check, not proof
that a Creality Print version can produce correct G-code in headless mode.
Creality 7.x builds have had documented Linux CLI issues. A real fixture using
self-contained native printer/process/filament profiles, output G-code
inspection and a print comparison is still required before declaring the
Creality integration complete. Do not rely on a smoke check alone for a
production print.

The engine is never allowed to start a printer automatically.

## MakerVault-reviewed OrcaSlicer 2.5.0 — K2 compatibility

**Never substitute the stock upstream OrcaSlicer 2.5.0 AppImage for the Creality K2 profile.** Creality's K2 machine preset specifies `retraction_distances_when_cut = 30 mm`, whereas stock Orca 2.5.0 rejects values above 18 mm. Our independently compiled binary adjusts exactly that source validation maximum to 30 mm without editing official profiles, and passed native K1, K2 and two-tool G-code tests in [Actions run 43789319270](https://github.com/gavrd7/MakerVault/actions/runs/43789319270).

Reviewed AppImage SHA-256: `b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054`.

The browser installer must resolve **only** the dedicated reviewed binary prerelease tag `orca-2.5.0-mv1`, asset `MakerVault-OrcaSlicer-2.5.0-mv1.AppImage`. The official GitHub release API's asset digest must match the pinned SHA-256, and the streamed download is verified a second time before extraction and activation. **If that audited prerelease does not exist, is unreachable or has a different checksum, version 2.5.0 must not be offered.**

The passing build artifact expires **23 November 2026 at 01:59 UTC**. To make the reviewed executable durably available, an authorised maintainer must register and manually run `.github/workflows/orca-reviewed-release.yml` on the default branch with approval text `PUBLISH-ORCA-2.5.0-MV1` **before that expiry**. The workflow retrieves only the exact reviewed Actions run and refuses to publish a different SHA-256; it creates an isolated binary prerelease, **not** MakerVault v1.7.0, and never auto-enables an engine. Do not merge unfinished engine-management changes solely to register this release workflow; use a separate workflow-only PR if needed before artifact expiry.

Orca 2.4.2 remains an intentionally separate, pinned **upstream** option for deliberate version downgrade. It has **not** been K2-source-patched or validated for this native 30 mm cut-retraction case. Future custom engine builds must receive a distinct independently pinned release and compatibility acceptance.

## Switching versions and uninstalling

- **Switch** selects an older (or newer) *already installed* engine version.
  The installer re-hashes the exact recorded executable before activation and
  leaves the other engine selections and binaries untouched.
- **Update / Install** obtains a previously uninstalled official version with
  the same independent integrity checks. An installed engine's previous
  version remains on disk for later selection.
- **Uninstall** requires a separate confirmation and removes the selected
  engine's installed versions, not the other engines. All existing MakerVault
  models, G-code files, user libraries and printer records are preserved.
  A deleted engine must be reinstalled before it can slice again.
- Active queued/running slicing jobs block engine changes; concurrent engine
  operations are also blocked. The service uses an atomic active-manifest
  update and checks version-directory safety before removing the selected
  engine's files.
- Only verified historical versions appear as switch candidates. Legacy
  installed versions without a recoverable SHA-256 identity are deliberately
  excluded until independently verified.

A missing **installer service** prevents installations, removals and switches,
but does not disable an already healthy worker. Initial opt-in deployment of
that separate service is a one-time infrastructure task; regular engine
management is browser-operated and **does not require the user to be a host
administrator**.

## Access policy

Signed-in users can manage engines by default. A team administrator may opt
into a restriction under Django Admin → Slicer engine access settings.
Checksum, source validation and runtime health checks always run
automatically; they are not approval tasks for end users.

## Troubleshooting

- **Installer not connected:** verify the opt-in service started with the
  private token and is healthy; it has no exposed host port.
- **No releases listed:** GitHub release API may be unavailable or no supported
  official Linux asset with a SHA-256 digest was found.
- **Verification failed:** the downloaded bytes or runtime failed an automated
  check; the previous active engine remains unchanged.
- **Creality CLI failed:** do not bypass this gate. Capture the installer status,
  validate the Linux AppImage/runtime dependencies and run a real CLI fixture.
- **Orca missing:** do not delete the engine volume. Verify the existing
  `slicer-engine-assets/manifest.json` and the previously staged Orca binary.

Never run `docker compose down -v` while the engine volume is in use.
