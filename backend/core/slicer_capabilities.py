"""Version-scoped native feature capability contract for the MakerVault editor.

A draft editor can store an annotation before its native exporter exists.
Never advertise a native feature as supported merely because the upstream
slicer has a similar tool. Only reviewed real-engine fixtures may upgrade
a feature to verified.
"""

FEATURES = {
    "colour_paint": "Colour painting",
    "support_paint": "Support painting",
    "seam_paint": "Seam painting",
    "fuzzy_skin_paint": "Selective fuzzy skin painting",
    "variable_layer_profile": "Variable layer height",
}

# No native surface painting exporter has passed a pinned-binary fixture yet.
# Orca's editor is ready for draft-only testing; other formats are not.
ORCA_DRAFT_VERSIONS = frozenset({"2.4.2", "2.5.0"})


def native_capabilities(engine, version):
    if engine == "orcaslicer" and version in ORCA_DRAFT_VERSIONS:
        state = "draft_only"
        reason = ("Editable in MakerVault drafts; native Orca export is not "
                  "yet verified, so these edits cannot be sliced.")
    elif engine == "cura":
        state = "incompatible"
        reason = ("No accurate native conversion is implemented for this Cura "
                  "adapter. Preserve the edit and use a compatible, verified "
                  "engine when available.")
    else:
        state = "unverified"
        reason = ("This engine/version has no verified native conversion for "
                  "these annotations. Try the OrcaSlicer editor for draft "
                  "work; native slicing is still pending.")
    result = {key: {"status": state, "reason": reason} for key in FEATURES}
    if engine == "prusaslicer" and version == "2.9.7":
        result["support_paint"] = {
            "status": "verified",
            "reason": ("Native Prusa 2.9.7 support enforcer and blocker masks "
                       "passed genuine, same-geometry CLI support-path comparisons. "
                       "Limited to one upright, unscaled, single-material model "
                       "without mixed native extensions; manual enforcer slices "
                       "must generate real support extrusion."),
        }
        result["fuzzy_skin_paint"] = {
            "status": "verified",
            "reason": ("Native Prusa 2.9.7 selectively altered external walls without "
                       "changing the unpainted neighbour in a genuine two-object "
                       "G-code comparison. Supports one or two upright unscaled "
                       "single-material models, exactly one painted in two-model "
                       "jobs, and no unqualified mixed native extensions."),
        }
        result["variable_layer_profile"] = {
            "status": "verified",
            "reason": ("PrusaSlicer 2.9.7 native per-object ranges passed real-binary "
                       "G-code Z-step acceptance, including two independent "
                       "models retaining separate layer schedules. Currently up "
                       "to two upright, unscaled, non-elevated single-material "
                       "models without unqualified native combinations."),
        }
    if engine == "crealityprint" and version.startswith("7.3."):
        result["colour_paint"] = {
            "status": "test_only",
            "reason": ("Creality native 3MF colour-painted facets can be sliced "
                       "on one object using two assigned CFS filaments. Confirm "
                       "real toolpath colour boundaries before considering the "
                       "physical test complete."),
        }
        for key, title in (
            ("support_paint", "Support"),
            ("seam_paint", "Seam"),
            ("fuzzy_skin_paint", "Selective fuzzy skin"),
            ("variable_layer_profile", "Variable layer height"),
        ):
            result[key] = {
                "status": "test_only",
                "reason": (title + " native export is experimental for one "
                           "Creality 7.3.x colour-painted CFS model with two "
                           "assigned filaments. Inspect generated G-code; "
                           "ordinary single-filament Creality slicing and "
                           "printer submission are not approved for this mode."),
            }
    if engine == "orcaslicer" and version == "2.5.0":
        result["fuzzy_skin_paint"] = {
            "status": "test_only",
            "reason": ("Painted-only fuzzy skin facets can be tested offline on a "
                       "single upright Orca 2.5.0 object. Inspect texture paths "
                       "before any printer submission."),
        }
        result["seam_paint"] = {
            "status": "test_only",
            "reason": ("Native seam enforcer/blocker facets are available for offline "
                       "single-object Orca 2.5.0 tests. Confirm actual seam "
                       "placement before printer submission."),
        }
        result["support_paint"] = {
            "status": "test_only",
            "reason": ("Support enforcer/blocker export is available for offline "
                       "single-object Orca 2.5.0 tests. Printer submission is "
                       "blocked until native supports are validated."),
        }
        result["variable_layer_profile"] = {
            "status": "test_only",
            "reason": ("Native Orca layer_config_ranges export is enabled for offline "
                       "single-model test slices. Printer upload is disabled until "
                       "real G-code layer transitions are verified."),
        }
    return result


def annotated_features(plates):
    """Identify used annotations; never treat an empty edit container as active."""
    used = set()
    for plate in plates:
        for item in plate.get("objects", []) if isinstance(plate, dict) else []:
            if not isinstance(item, dict):
                continue
            for key in FEATURES:
                value = item.get(key)
                if not isinstance(value, dict):
                    continue
                if value.get("regions") or value.get("faces") or value.get("bands"):
                    used.add(key)
    return sorted(used)


def native_compatibility_errors(engine, version, plates):
    caps = native_capabilities(engine, version)
    return [
        {"feature": key, "label": FEATURES[key], **caps[key]}
        for key in annotated_features(plates)
        if caps[key]["status"] != "verified"
    ]
