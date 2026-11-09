# Native and MakerVault build-plate artwork

The Creality K1 and K2 SVGs bundled here are unmodified build-plate
textures sourced from **OrcaSlicer v2.4.2**:

- [Creality K1 SVG](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Creality/creality_k1_buildplate_texture.svg)
- [Creality K2 SVG](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/resources/profiles/Creality/creality_k2_buildplate_texture.svg)

Source: https://github.com/OrcaSlicer/OrcaSlicer
Licence: **AGPL-3.0** (subject to any separately stated upstream artwork terms).
MakerVault does not claim ownership of the manufacturer artwork.

`makervault-official-logo.svg` contains a compact, transparency-adjusted
rendering of the MakerVault logo supplied by the project owner. It replaces
the previous generic placeholder symbol on the procedural 3D fallback plate.

## Profile-driven native artwork

The authenticated profile plate API can return a same-origin `artwork_url`
for an owned, hash-verified, official OrcaSlicer machine preset that directly
declares a safe `bed_texture` filename. This is not a general arbitrary-URL
download feature.

On first viewing the profile, the associated artwork endpoint fetches the
asset from the **pinned OrcaSlicer v2.4.2 source**, checks a size limit and
rejects SVG scripts, external links, foreign elements and other active content,
then caches the approved content locally. Later requests work offline when
the local cache exists. Missing, unsupported and unsafe artwork falls back to
MakerVault's generic 3D plate. Artwork never changes G-code or printer support.

The built-in K1/K2 assets remain as offline starter artwork even without an
imported printer profile. Normalisation ignores the descriptor `Combo`, but
not distinct hardware variants such as `Plus`, `Pro`, `Max` or `SE`.
Native artwork can be disabled in the visual editor.

## Current limitations / next adapters

- This first imported-art adapter supports explicit `bed_texture` on official
  OrcaSlicer **v2.4.2** printer presets only; it does not yet resolve inherited
  texture declarations.
- It does not ingest native 3D `bed_model` geometry.
- Additional installed versions, Creality Print, Bambu Studio, PrusaSlicer,
  Snapmaker Orca and Cura require separately validated metadata readers and
  source/format handling.
- The server downloads on **first artwork request**, not automatically when
  importing a large batch of profiles. Downloads should remain bounded and
  must never grant enhanced Docker privileges or arbitrary network access.
