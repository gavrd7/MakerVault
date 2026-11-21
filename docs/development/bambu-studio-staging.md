# Bambu Studio 02.09.01.70 — isolated candidate acceptance

**Status: development candidate only.** The OrcaSlicer/Creality Print foundation in PR #171 is merged. This follow-on Bambu work belongs to draft PR #191; neither the main application nor the normal worker is allowed to use Bambu for jobs until the pinned real-binary and native-profile acceptance pass.

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

## Still required for v1.7.0 Beta

1. Real official binary download, checksum verification, image extraction and executable startup in a controlled container.
2. Pin matching original Bambu machine/process/filament resources and demonstrate one real STL -> single-material G-code result; inspect firmware commands and output metadata.
3. Repeat with genuine 3MF and supported printer profiles, then verify material/tool semantics.
4. Only after acceptance: explicitly approve Bambu in the engine registry, bind its runner in the worker, coordinate backend engine/catalogue/installer support and enable it as **Beta**.
5. Re-run backend, frontend, worker, Docker, licence/security and staging tests. Publish MakerVault v1.7.0 before merging the separate public guide PR #40.

No real Bambu binary was downloaded into the repository or user staging server by these commits. Binary acquisition is performed by the explicit host-side command above.
