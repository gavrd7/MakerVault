# Bambu Studio 02.09.01.70 — isolated candidate acceptance

**Status: development candidate only.** The OrcaSlicer/Creality Print foundation PR #171 and four-container engine-management PR #192 are merged. This follow-on Bambu work belongs to draft PR #191; Bambu is not yet in the main application's approved engine registry, the combined installer catalogue or normal worker request routing. Do not deploy the optional candidate image over the running `makervault-slicer` service.

## Official Linux executable

Official upstream [Bambu Studio v02.09.01.70](https://github.com/bambulab/BambuStudio/releases/tag/v02.09.01.70) release asset:

- Ubuntu 24.04 AppImage: `BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage`
- SHA-256: `668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0`
- Source: exact `github.com/bambulab/BambuStudio/releases/download/v02.09.01.70/` URL.
- Acquire via **GitHub's official release API** and independently hard-coded pinned SHA-256. A missing/changed digest fails closed. Upstream code and binary remain under their respective vendor licences; **never commit a ~244 MiB AppImage to MakerVault Git**.

### Prepare in a clean disposable checkout

The downloader **refuses** any non-empty `slicer-engine-assets/` directory to protect existing Orca and Creality installations. On the Debian staging server, use a separate clean checkout/build context, **not** the live staging installation or its working `.slicer-staging.env`.

```bash
# In a separate disposable checkout of PR #191:
python3 scripts/prepare_bambu_staging.py
sha256sum slicer-engine-assets/bambustudio.AppImage

# Builds an image with the original SHA-pinned binary and an unpacked
# in-bundle AppRun entrypoint; does not enable the engine.
docker build -f slicer_worker/Dockerfile.bundle \
  -t makervault-bambu-candidate:local .
```

No host/worker privileges or Docker socket should be granted to the MakerVault web application. The candidate image uses a separate `/opt/engines/bambu-root/squashfs-root` extraction tree. Do not replace the existing Orca worker image, volume or environment with the Bambu candidate.

## Offline CLI acceptance with real native profiles

Before attempting a physical print, independently prepare complete, exact-version Bambu Studio `printer.json`, `process.json` and `filament.json` profiles, including verified inheritance and genuine printer-specific G-code macros. Do not use invented fixture JSON or copy native Orca profiles merely because the formats look similar.

Run the probe **inside an isolated candidate container** with `--network none`, a read-only root filesystem, bounded CPU/memory/PIDs and only the required read-only native-profile fixture mount. The worker itself has no engine activation token, live printer connector, cloud credentials or host Docker socket. A sample shell recipe (replace the fixture path with the verified local directory):

```bash
docker run --rm --network none --read-only --pids-limit 128 \
  --cpus 2 --memory 3g --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --mount type=bind,src="$(pwd)/bambu-fixtures",dst=/fixtures,readonly \
  --entrypoint python3 makervault-bambu-candidate:local \
  -m slicer_worker.probe \
  --engine bambustudio --version 02.09.01.70 \
  --binary /opt/engines/bambu-root/squashfs-root/AppRun \
  --printer /fixtures/printer.json \
  --process /fixtures/process.json \
  --filament /fixtures/filament.json \
  --timeout 180
```

The probe generates a small tetrahedron STL, exercises the actual Bambu CLI using scratch-only profiles, extracts exactly one `Metadata/plate_N.gcode` from the native sliced 3MF, and checks for real extrusion G-code. It reports bounded SHA-256/size/profile receipts without exposing G-code, output paths, keys or arbitrary CLI logs. Adjust container limits to support the real AppImage if necessary; never remove network isolation or pass live printer credentials.

A **successful fixture** is evidence for this binary and one specific set of profiles only; it is not approval for other profiles, multicolour/toolheads, CFS/AMS mapping, printer dispatch or use with unrelated printers. If the CLI fails, first confirm Bambu-specific runtime resources and native-profile lineage rather than disabling MakerVault's safety validation.

## Verified native-profile and isolated slicer smoke

The dedicated Bambu Actions workflow downloads and verifies the **official, SHA-256-pinned AppImage** and extracts its actual native runtime. For a real representative Bambu configuration, `scripts/prepare_bambu_native_fixtures.py` resolves the **X1 Carbon 0.4-mm / Standard 0.20-mm / Bambu PLA Basic** fixture from the **same extracted executable's bundled BBL profiles**. It follows locally present native `inherits` and explicit `include` records and rejects missing, ambiguous, cyclic or oversized chains. Vendor G-code include fragments with an intentionally absent profile `type` may be resolved only as explicit includes, never as root machine/process/filament profiles.

**Verified evidence (22 November 2026):**

- Real pinned Bambu Studio 02.09.01.70 CLI headless startup passed on Ubuntu 24.04.
- Real native, single-material tetrahedron STL slice passed, producing **137,742 bytes** G-code with extrusion: SHA-256 `9436bc7314d765588ca4cb7f450b16a422e7f2ec014b9b1659e4cf6b4d4d42ec`.
- Real fixed, one-object MakerVault **core 3MF** slice passed, producing **137,694 bytes** G-code with extrusion: SHA-256 `3eb12097cafd0a7864e4110431091ebd37b4aba0aadea72db52437655e0286e9`.
- Both **STL and 3MF** passes repeated successfully inside the *disposable Bambu candidate Docker image*, using a non-root process, read-only rootfs, `--network none`, all Linux capabilities dropped, bounded resources, and read-only native-profile fixtures.
- Passing run: [Bambu pinned Linux AppImage candidate #44983450397](https://github.com/gavrd7/MakerVault/actions/runs/44983450397). This is real executable evidence, not mocked fixture success or merely an extracted binary.

A pinned executable's `AppRun` SHA-256 differs from the original AppImage hash. The approved provenance remains the original official AppImage SHA-256 `668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0`, with extracted runtime integrity established by the build and probe.

The real native runtime needs Ubuntu GStreamer and WebKit packages. The candidate Dockerfile includes the tested dependencies. Its existence does **not** make it a production `Dockerfile.generic` image; no new long-lived Bambu container is authorized.

**What the passing test does not yet prove:** general Bambu profile catalogue compatibility, arbitrary native project 3MF, physical print output, colour/tool assignments, AMS/CFS mapping, or that the installed Bambu binary works in the existing four-container UID-separated runtime. The normal MakerVault worker/service still rejects `bambustudio` and the installer does not offer it.

### Integration into the merged four-container architecture

Preserve the combined `makervault-slicer` service introduced by PR #192 and its independent installer/worker UIDs and tokens. The accepted next stage is:

1. Admit the exact approved Bambu release through the existing installer catalogue only with official URL, SHA-256, verified downloaded bytes, headless CLI probe and atomically published versioned store. Preserve Orca and Creality installations and rollback behaviour.
2. Ensure the combined worker image provides the required native shared libraries and correct bundled application resources; exercise a real Bambu installed-version slice **as UID 10001** with the store read-only to that UID and the existing seccomp egress policy.
3. Add explicitly gated worker engine registry/request routing and backend engine/profile discovery. Do not treat an approved binary alone as approval for arbitrary native presets; maintain inheritance resolution and profile sanitization.
4. Expose Bambu Studio as **Beta** in the existing UI only after the above passes, with normal operation audit, permissions, and absence of automatic printer dispatch.
5. Add real installer lifecycle, native STL/3MF, multi-profile isolation, app/UI, security and staging regressions. Keep multicolour and physical printer acceptance distinct from single-material support.

No physical printer has been contacted or sent a job by any work on this PR. Existing OrcaSlicer and Creality Print containers and engine volumes were not modified.

## Remaining for v1.7.0 Beta

- [x] Official Bambu AppImage SHA-256, real executable startup, native X1C profile ancestry and offline STL slicing.
- [x] Genuine fixed core 3MF input slicing, single-plate G-code extraction and actual extrusion evidence.
- [x] Same real input formats pass in a disposable, non-root, networkless read-only Docker candidate.
- [ ] Integrate verified Bambu installation/runtime into the existing combined worker/installer volume and process isolation; no fifth container.
- [ ] Integrate the approved engine, native profiles and explicit beta state into Django/worker/UI, then confirm equivalent end-to-end slicing in staging.
- [ ] Confirm actual generated firmware G-code and printer compatibility; separately verify multicolour/AMS semantics before enabling them.
- [ ] Reconcile this draft PR branch with merged #192, run complete latest-head CI and user staging acceptance.
- [ ] Release v1.7.0 before separately publishing draft docs PR #40.
