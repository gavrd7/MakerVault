# In-browser slicer engine installation — four-container staging

MakerVault runs **four long-running containers**: application, PostgreSQL,
Redis and **one combined slicer runtime** (`slicer-worker`). The runtime
supervises two unprivileged subprocesses on separate UIDs: the slicer HTTP
worker (10001, port 8088) and the authenticated engine installer (10002,
port 8091). The shared versioned engine store is owned by installer UID
10002 and readable but **not writable** by worker UID 10001. The worker's
permanent Linux seccomp filter denies outbound `connect(2)`, including to
child slicer binaries; the installer retains verified release downloads.
Worker and installer tokens are removed from the other process's environment.
No Docker socket, app database, media or printer mounts are provided.

Unlike the original two-container setup, the combined container has a
shared network namespace and a root PID-1 supervisor with only SETUID and
SETGID capabilities. The UID, environment and seccomp restrictions are
security measures, not full equivalence to separate-container isolation.
Do not deploy without passing container integration checks and staging
acceptance. The `slicer-engine-store-init` Compose helper is a short-lived
**exited** permission-migration task, not a fifth running service.

## Migrate an existing staging installation

**Only after PR #192 CI passes**, from the checked-out PR branch:

```sh
cd ~/MakerVault-Staging
git pull --ff-only
sudo python3 scripts/install_slicer_staging.py consolidate-slicer
sudo python3 scripts/install_slicer_staging.py update
```

**Existing engine volume permissions:** Older `versions/orcaslicer/2.5.0`
and `versions/crealityprint/7.3.1` directories may be private to the
former worker UID. The one-time migration helper uses `CHOWN`, `FOWNER`
and `DAC_READ_SEARCH` strictly for traversal and ownership migration.
It always reprocesses the full tree on retry (rather than skipping when only
the volume root was previously changed). It does **not** grant these caps
to the persistent worker. A locked-directory fixture is exercised by the
combined-container smoke test.

If the previous migration failed at `slicer-engine-store-init`, preserve
the stopped legacy installer and the engine volume. Check
`sudo docker logs makervault-slicer-engine-store-init-1`, pull this
corrected PR branch, verify an engine-volume backup (an interrupted tar is
not a valid backup), then explicitly rerun `consolidate-slicer`. Do
not remove orphan containers or pass `--remove-orphans` until both native
engines have passed real on-host slicing tests.

The migration checks the full Compose configuration, stops the **old**
standalone engine installer, stops the previous worker, adjusts permissions
on the existing versioned volume **without deleting it**, then builds and
starts the combined `slicer-worker`. It does not change printer or inventory
data, user G-code or tokens. Check `sudo docker compose ... ps` and verify
both installer connectivity and K2/Creality slicing. The old installer remains
as a **stopped** rollback container until explicitly removed.

After successful acceptance only, remove the stopped legacy container:

```sh
sudo docker rm makervault-slicer-engine-installer-1
```

Never use `docker compose down -v` or `docker system prune` for this
migration. On subsequent UI-only changes, `update` rebuilds the main app;
slicer code changes use `refresh-worker` to rebuild the combined image.
Existing staging users should **not** run the old five-container installer
build command again.

## Engine installation and version management

The installer discovers **Creality Print** releases through the official
`CrealityOfficial/CrealityPrint` GitHub releases API, checking each Linux
x86-64 AppImage against its published SHA-256. **OrcaSlicer** offers the reviewed MakerVault K2-compatible 2.5.0 binary embedded in its immutable GHCR-based installer image, plus independently pinned upstream 2.4.2 for deliberate older-version selection. This includes
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
   extracts the AppImage inside the installer child process.
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

## MakerVault-reviewed OrcaSlicer 2.5.0 — safe reinstall

The Creality K2's native profile specifies `retraction_distances_when_cut = 30 mm` but the stock OrcaSlicer 2.5.0 binary rejects values above 18 mm. MakerVault compiled the reviewed source correction which changes that **one validation limit** to 30 mm, while preserving the manufacturer profile. The reviewed binary passed K1, K2 and two-tool CLI slicing acceptance in [Actions run 43789319270](https://github.com/gavrd7/MakerVault/actions/runs/43789319270).

Reviewed AppImage SHA-256: `b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054`.

**No extra release or container is required.** The combined slicer runtime is built from `slicer_worker/Dockerfile.generic`, which pins the reviewed Orca bootstrap image by **immutable GHCR manifest digest** (`ghcr.io/gavrd7/makervault-slicer-orca@sha256:7f12df990d059d6a5e889c3cff6ebacd3a7c627fee28ff75e8696bee9c3423f4`). The installer checks the bundled `/opt/engines/orcaslicer.AppImage` against that approved SHA-256, copies it into the versioned engine volume, checks the copy again, and activates the known-good runtime. **It never downloads the stock upstream 2.5.0 AppImage**, and refuses installation if the bundled source is missing or modified.

For a staging checkout that previously installed the incompatible stock Orca 2.5.0, first deploy/rebuild the **combined slicer runtime** and main application from this PR, then explicitly uninstall only Orca from the browser and reinstall 2.5.0 through the version dropdown. Existing Creality installations and MakerVault records must remain untouched. The installer will not silently overwrite an existing version directory. Verify the original Creality K2 native profile can generate a real Benchy G-code before marking the PR merge-ready.

Orca 2.4.2 is a separate pinned upstream version, **not K2-approved** for the 30 mm cut retraction compatibility issue. Other engines still use checksum-verified native release downloads. Keep one shared slicer worker container; do not add a new Orca container, Docker socket access or host write privileges to the web app.

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

An unhealthy **installer child** prevents installations, removals and switches;
the combined container health requires both processes. Initial four-container
migration is a one-time infrastructure task; regular engine
management is browser-operated and **does not require the user to be a host
administrator**.

## Access policy

Signed-in users can manage engines by default. A team administrator may opt
into a restriction under Django Admin → Slicer engine access settings.
Checksum, source validation and runtime health checks always run
automatically; they are not approval tasks for end users.

## Troubleshooting

- **Installer not connected:** verify the combined runtime started with the
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
