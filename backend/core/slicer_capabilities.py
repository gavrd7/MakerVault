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
    if engine == "orcaslicer" and version == "2.5.0":
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
