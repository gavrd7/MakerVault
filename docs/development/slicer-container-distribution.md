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

- Publish **two images**: `ghcr.io/gavrd7/makervault:<app-version>` and
  `ghcr.io/gavrd7/makervault-slicer-orca:2.5.0-mv1` (example tag).
  The web app image must not contain Orca or its heavy graphical dependencies.
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
