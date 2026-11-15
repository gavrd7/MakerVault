# OrcaSlicer 2.5.0 official-profile CLI compatibility

## The upstream mismatch

At tag `v2.5.0` (commit `40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19`),
`resources/profiles/Creality/machine/Creality K2 0.4 nozzle.json` specifies:

- `enable_long_retraction_when_cut = 2`
- `long_retractions_when_cut = 1`
- `retraction_distances_when_cut = 30`

The same release's `src/libslic3r/PrintConfig.cpp` defines
`retraction_distances_when_cut` with an upper bound of **18**, and its CLI
runs `m_print_config.validate(true)` before slicing. Thus a fully inherited
official K2 profile is rejected for a setting the manufacturer provided.

This is an **engine source inconsistency**, not a missing user-editable field or
a MakerVault profile import error. The usual K2 smoke fixture previously
adjusted 30 to 18 *for test only*; it does not prove the official profile works.

## Corrected-engine approach

`scripts/orca_compatibility_patch.py` is intentionally restricted to the exact
Orca 2.5.0 commit. It changes the engine's schema upper bound **18 → 30 only
for `retraction_distances_when_cut`**. All other native validation remains
enabled; no vendor profile is rewritten. This does not permit arbitrary
retraction distances and is **not** a general numeric-validation bypass.

The build uses the actual Orca source and must generate a **new AppImage**.
Changing MakerVault's Python code or refreshing the existing official
AppImage **cannot** modify the already compiled CLI maximum.

The manual GitHub Actions workflow
`.github/workflows/orca-reviewed-compatibility.yml`:

1. Verifies the exact upstream source revision and applies the narrow patch.
2. Builds a candidate AppImage from source.
3. Uses the usual checksum-pinned, isolated worker container.
4. Requires real G-code generation with **unchanged** official K1 and K2
   printer, process and filament settings.
5. Requires an offline K2 two-tool G-code test.
6. Publishes an AppImage artifact and SHA-256 **only after those checks pass**.

This manually triggered workflow does not automatically install or approve a
binary, upload G-code to a printer, or turn on execution. It is available for
manual dispatch once the workflow file is present on the GitHub default branch.
A passing workflow validates software generation only, **not physical CFS
filament handling** or machine safety. Real print acceptance remains separate.

## Controlled staging installation after a successful build

Download the **tested AppImage** from the completed manual workflow and
independently verify its SHA-256 before invoking:

```bash
cd ~/MakerVault-Staging
python3 scripts/install_slicer_staging.py upgrade-reviewed-orca \
  --reviewed-appimage /path/to/reviewed-orca.AppImage \
  --reviewed-sha256 THE_APPROVED_64_HEX_SHA256
```

This is intentionally explicit. The installer verifies the binary bytes
before touching staging, checks the existing worker identity, keeps the
current native version identity (`2.5.0`) so previously downloaded native
profiles remain compatible, and preserves the old binary/configuration as
`*.pre-upgrade`. It rebuilds the worker with the new digest and uses the
existing rollback mechanism on an upgrade failure. Do **not** run the command
with the unchanged official AppImage; the original error would remain.

Before executing any generated G-code on hardware, check the native print
settings, tool/filament changes, and machine-specific commands. Testing must
include a K2 single-filament Benchy first, then CFS changeovers separately.

## Future updates and engines

This correction is **version pinned**: if Orca changes its schema, this patch
fails rather than silently editing an unknown release. The manual build
checks deliberately use unmodified source profiles. Other slicing engines
must have their own tested compatibility checks; global numeric clamps,
automatic stripping of out-of-range values, and disabling configuration
validation are not acceptable general strategies.

Prefer an upstream Orca correction and an unmodified approved binary when the
upstream mismatch is resolved. Until then, retain the source provenance,
build digest and offline regression evidence with each reviewed engine.
