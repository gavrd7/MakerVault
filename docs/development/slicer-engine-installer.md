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
git pull --ff-only origin feature/self-hosted-slicer-foundation
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

## Creality Print first candidate

The source is exclusively the official
`CrealityOfficial/CrealityPrint` GitHub releases API. Only released, non-beta
Linux x86-64 AppImages with a published GitHub SHA-256 digest appear as
installation candidates. The release metadata is cached for ten minutes.
Direct user-provided download URLs, commands and paths are not accepted.

1. The user chooses an available version and clicks **Install**.
2. MakerVault sends an authenticated request to the installer (internal network only).
3. The installer downloads official bytes with bounded redirects and size,
   compares the final SHA-256 against the official release metadata and
   extracts the AppImage inside its restricted container.
4. It attempts the fixed, bounded headless `AppRun --help` compatibility check.
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
