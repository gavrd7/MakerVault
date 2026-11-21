# Reviewed OrcaSlicer Docker distribution plan (development)

## Current status (16 November 2026)

The source-corrected OrcaSlicer 2.5.0 AppImage passed the K1, K2, and
two-tool K2 CI slicing fixtures in workflow #43789319270 and was installed
manually into a staging-only worker. This is NOT a production approval.
The artifact expires after seven days and must not be used as a permanent
installation source.

Source identity: OrcaSlicer v2.5.0 at
`40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19`.
The reviewed compatibility correction is applied by
`scripts/orca_compatibility_patch.py`.
The accepted AppImage digest from the staging operator is
`b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054`.
Pin that digest in an independently reviewed release manifest, not just a
mutable Actions cache. Keep the exact upstream source revision, patch revision,
binary digest, base OS, and worker image digest traceable.

## Recommended release architecture

- Publish **two images for the initial bootstrap**: `ghcr.io/gavrd7/makervault:<app-version>` and
  `ghcr.io/gavrd7/makervault-slicer-orca:2.5.0-mv1` (example tag).
  The web app image must not contain Orca or its heavy graphical dependencies. **All slicer engines share one slicer-worker container**; this first Orca image is only the initial bootstrap of that single container, not a separate worker to be run alongside future engine containers.
- Base the engine image on `slicer_worker/Dockerfile.bundle` and the
  independently checksum-verified AppImage. Preserve the original AppImage
  inside the image for the worker's runtime hash verification.
- Use a dedicated, opt-in Compose service connected by an internal network.
  Leave the worker disabled by default for existing installations.
  Never bind Docker socket, application media, PostgreSQL, Redis, or host
  credentials into the worker. No publicly exposed worker ports.
- Pin the image in deployment by **registry manifest digest**,
  `ghcr.io/gavrd7/makervault-slicer-orca@sha256:<digest>`, and pin the
  internal Orca executable by SHA-256. Keep a per-engine version/approval
  registry; verify worker health identities before enabling execution.
- Use a secure per-installation worker token. Supply it to only the main
  application and the worker through a restricted env/secret mechanism.
- Keep exactly one optional `slicer-worker` service, regardless of how many engines are installed. As more engines are supported, install independently verified runtime bundles into a dedicated persistent engine volume (with atomic versioned directories, safe activation, and rollback). Do not use one long-running container per engine and do not install them only in the container writable layer.
- Keep one operator-facing install command that composes the existing
  app, database, Redis and optional worker. Existing plain MakerVault
  installations must remain fully usable without a slicer worker.
- Offer an independently selectable release channel for the worker so
  an app update never silently replaces an approved engine. Keep previous
  digest and binary identity available for rollback.

## Publish gate

1. Rebuild on a trusted, reproducible CI runner from pinned upstream Orca
   source + reviewed patch. Require a clean diff and source-patch tests.
2. Require unchanged official K1/K2 profiles to generate nonempty real G-code,
   plus the K2 two-tool fixture. Check engine version, tool/material changes,
   timings and output metadata. Add end-to-end MakerVault UI/API tests.
3. Run dependency and container security checks, inspect licenses and include
   upstream attributions, source and patch availability, and supply-chain
   attestations/SBOM. Validate Dockerfile/worker permissions.
4. Push a dedicated, explicitly approved image to GHCR; record its immutable
   manifest digest and the binary digest in the release manifest.
5. Test `docker compose pull`, initial opt-in, update, disable, rollback and
   persistent drafts on a clean Linux x86-64 host. Test fresh installs and
   upgrades from older MakerVault installations without a worker.
6. Do NOT claim ARM64 support on the basis of MakerVault's app image:
   this patched AppImage is Linux x86-64. Publish the worker for amd64 only
   until an ARM64 Orca binary is independently built and tested. Document
   unsupported hosts without emulating a production slicer.
7. Advance from staging to general availability only after native painting,
   profile inheritance, multi-material and generated-G-code tests meet
   explicit acceptance criteria. Never auto-start printer jobs.

## Work remaining

- Build and publish the dedicated image from the exact reviewed executable.
  Current `publish-container.yml` builds the main app only; add a separate,
  explicitly gated worker-publish workflow rather than adding the Orca binary
  to the regular app image.
- Extend `compose.slicer.yaml` to the approved multi-engine registry and
  digest-pinned image contract used by `compose.slicer.staging.yaml`.
- Add a supported installer/uninstaller and migration path for regular users,
  which obtains the image from GHCR rather than the expiring workflow ZIP.
- Keep the current staging installer as a development-only fallback.
- Resolve native fuzzy skin painting, seam/support painting, variable-layer
  export, and full multi-material execution gates before advertising parity.

## Verified 2.5.1 maintenance release investigation (16 November 2026)

Upstream OrcaSlicer v2.5.1 was published 2026-11-14, tag
`eef7710cb102fdb51a9bcdbd9efd61047f44774a`.
We inspected the upstream tag's `src/libslic3r/PrintConfig.cpp` and
confirmed the `retraction_distances_when_cut` definition STILL has
`def->max = 18`. Its official Creality K2 profile requires 30 mm.
This is not fixed in that hotfix; do not silently replace our validated
patched 2.5.0 with unpatched upstream 2.5.1.

## Initial GHCR publication workflow

`.github/workflows/publish-orca-worker.yml` is an explicit,
operator-approved release packaging path. It downloads ONLY the exact CI
artifact from workflow run `43789319270` and requires executable SHA-256
`b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054`.
It stages the engine with its manifest, builds a container, verifies the
contained executable hash, then pushes a Linux AMD64-only GHCR image.
The workflow never automatically starts or upgrades a worker.

**Release blocker:** GitHub requires a `workflow_dispatch` workflow to be
present on the repository's default branch for manual dispatch. Review and
merge this *release workflow only* into main when ready, without merging
unfinished slicer application changes. The workflow checks out the named
slicer branch to build but the verified AppImage checksum remains fixed.
The source artifact is retained for seven days; run the release build
before its expiry (2026-11-23), or first publish the reviewed binary in
an independently approved durable release with the same checksum.

**Operator configuration after successful GHCR publication:**

- Copy the image's **registry manifest digest** from the workflow summary.
- Define `MAKERVAULT_SLICER_WORKER_IMAGE` as
  `ghcr.io/gavrd7/makervault-slicer-orca@sha256:<approved-digest>`.
- Define `MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST` as exactly
  `sha256:<approved-digest>`.
- Define `MAKERVAULT_SLICER_ENGINES_JSON` as
  `{"orcaslicer":{"version":"2.5.0","binary_sha256":"b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054"}}`.
- Define `SLICER_ENGINES_JSON` as
  `{"orcaslicer":{"binary":"/opt/engines/orcaslicer.AppImage","version":"2.5.0","binary_sha256":"b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054"}}`.
- Generate a unique cryptographically secure 32+-byte
  `MAKERVAULT_SLICER_WORKER_TOKEN` and keep it in the host's restricted
  environment, never in source control.
- Set `MAKERVAULT_SLICER_EXECUTION_ENABLED=1` only after image approval,
  matching engine hashes and a healthy worker.
- Enable by selecting the optional overlay and `slicer` profile:
  `sudo docker compose -f compose.yaml -f compose.slicer.yaml --profile slicer up -d`.
  Avoid combining with the staging overlay; do not enable this experimental
  release on a live production installation before clean-host validation.

## Future in-app engine updates

The UI should manage multiple engine installations and versions **within one worker service**, not deploy new services per engine. The bootstrap Orca image is an intermediate distribution artifact; a future generic worker base plus volume-backed verified engine bundles will avoid rebuilding the image for every engine update. The UI should read a versioned, signed or trusted release index served by
MakerVault, not an arbitrary `latest` tag. It must show current engine,
available approved version, architecture support, release notes, binary and
image digests, validation coverage and the previous rollback target.

The administrator must explicitly approve **Download / Validate / Activate**.
A separate host-side updater (not the web app and never a mounted Docker
socket) performs GHCR pulls, digest verification, health checks and rollback.
The app reports the outcome and blocks activation while jobs are running.
An automated check for *available* releases can be enabled; automatic
activation should remain opt-in and disabled by default until the full
updater mechanism and safety gates are implemented.

## Generic single-container foundation (16 November 2026)

The first reviewed Orca image was successfully published and passed a genuine,
isolated, authenticated K2 test slice on the staging server. Its digest remains:
`ghcr.io/gavrd7/makervault-slicer-orca@sha256:7f12df990d059d6a5e889c3cff6ebacd3a7c627fee28ff75e8696bee9c3423f4`.

The **new** generic image build is `slicer_worker/Dockerfile.generic`. It
reuses that exact immutable image as its bootstrap, updates the common worker
implementation, and will be published as `ghcr.io/gavrd7/makervault-slicer:0.1.0`
only after its independent acceptance workflow passes. This is still
**one optional, long-running `slicer-worker` Docker container**, not a
separate service for every future engine.

The optional `compose.slicer.yaml` now adds a **single named engine volume**
`makervault_slicer_engines` mounted **read-only** inside the worker at
`/opt/engine-store`. This volume persists across container recreation.
The image-bundled Orca engine remains available when the volume has no
active registry. Engine updates must never run inside the worker process.

`slicer_worker/engine_registry.py` can read
`/opt/engine-store/active.json` with schema version 1 and selected engines.
It validates engine names, version/path confinement and exact binary SHA-256
before advertising engines as available. A malformed active registry
**fails closed**; it never falls back silently to an outdated image registry.
MakerVault still independently verifies the image digest and approved binary
hashes through its backend config, so an engine-store change alone cannot
authorize execution.

### Host-admin bootstrap and rollback (foundation; no UI yet)

`python3 -m slicer_worker.engine_store_admin` has explicit host-admin
commands to seed the exact reviewed Orca AppImage and extracted AppDir from
the immutable image into `versions/orcaslicer/2.5.0`, activate that installed
version and restore the previously approved selection. It must run **only**
in an ephemeral maintenance environment with a writeable engine-volume mount;
the web app and main worker never receive write access to this volume or the
Docker socket. A registry change must be coordinated with the application's
pinned engine approvals. No automatic updates or background download are
currently enabled.

The generic worker publishing workflow
`.github/workflows/publish-generic-slicer-worker.yml` verifies:
- Engine-store and rollback tests.
- An actual Docker volume seeded with the reviewed Orca binary, an activated
  registry, and a separate read-only worker view of the same volume.
- An isolated authenticated health and K2 G-code slice with the generic image.
- Publication to GHCR **only after all checks succeed**.

The publishing workflow must be registered on `main` through a
workflow-only review; it is not intended to merge unfinished feature
changes. The published image digest must be independently verified before
any staging image switch. No production migration or in-app updater is
claimed complete.

### Remaining milestones

1. Review and publish generic worker 0.1.0, capture its immutable digest.
2. Repeat isolated runtime tests and explicitly test switch/rollback on
   staging, without deleting the previous working image or saved projects.
3. Add a restricted host updater and signed/approved release catalogue for
   install/check/update/rollback. No Docker socket in the web app.
4. Connect the existing Engine Installations UI to approved availability
   information and updater status; updates require administrator consent.
5. Add one independently verified adapter/runtime bundle per future engine
   into **the same** versioned volume and existing worker service.
6. Complete native painting, variable layer, multi-material flushing and
   per-engine G-code acceptance separately.
