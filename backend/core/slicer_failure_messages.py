"""Safe, bounded explanations of isolated slicer worker failures.

Worker reasons are stable allowlisted categories, not arbitrary output text.
CLI exit statuses differ across Orca/Bambu versions. Never treat an exit code
alone as a definitive diagnosis, and never echo untrusted CLI output.
"""

REASONS = {
    "cli-validation-exit-238": (
        "OrcaSlicer rejected native profile or project settings (CLI exit 238). "
        "Check the printer, filament and process values for settings outside "
        "the range accepted by the installed OrcaSlicer version."
    ),
    "native-project-settings-invalid": (
        "OrcaSlicer reported out-of-range or invalid native project settings. "
        "Review the selected printer, filament and process presets."
    ),
    "cli-validation-exit-239": (
        "OrcaSlicer stopped during CLI validation (exit 239). "
        "A likely cause is a process preset incompatible with the printer's "
        "native machine identity. Check the printer/process pairing; "
        "the exit code alone does not prove this cause."
    ),
    "native-profile-load-failed": (
        "OrcaSlicer could not load one of the native printer, filament or process profiles. "
        "Check that each preset matches the installed engine version."
    ),
    "native-project-load-failed": (
        "OrcaSlicer could not read the generated 3MF project. "
        "Try slicing an unchanged STL, then review the plate layout and transforms."
    ),
    "unresolved-profile-parent": (
        "A native profile depends on a missing parent preset. "
        "Re-import the official preset to restore its complete parent chain."
    ),
    "unsupported-cli-option": (
        "The installed OrcaSlicer build rejected a command-line option. "
        "Check the pinned slicer engine version and worker installation."
    ),
    "qt-platform-failed": (
        "The OrcaSlicer graphical runtime failed to start in headless mode. "
        "Check the worker's Qt runtime and display configuration."
    ),
    "missing-runtime-library": (
        "The slicer runtime is missing a shared library. "
        "Rebuild or repair the isolated slicer worker installation."
    ),
    "appimage-runtime-failed": (
        "The OrcaSlicer AppImage runtime failed to initialise. "
        "Check the pinned engine extraction and worker installation."
    ),
    "invalid-stl": "The STL could not be validated. Re-export or repair the model and retry.",
    "invalid-3mf": "The 3MF project could not be validated. Check the plate geometry and retry.",
    "engine-timeout": "OrcaSlicer exceeded its allowed slicing time. Try a smaller model or review worker resource limits.",
    "no-output-directory": "OrcaSlicer did not create its expected output directory. Review the worker runtime.",
    "missing-gcode": "OrcaSlicer finished without valid G-code. Check the native profiles and model placement.",
    "unexpected-output-layout": "OrcaSlicer returned unexpected output files. Check engine and worker version compatibility.",
    "output-too-large": "Generated G-code exceeds the worker's configured size limit.",
    "invalid-gcode": "The generated G-code failed validation and was not saved or sent to a printer.",
    "engine-unavailable": "The approved slicer engine binary is unavailable. Check the worker installation.",
    "engine-version-mismatch": "The worker's installed slicer version does not match the approved version.",
    "engine-launch-failed": "The slicer executable could not be launched. Check the worker installation.",
    "unsafe-profile-settings": "The native profile contains a blocked command or network setting.",
    "invalid-profile-json": "A native profile contains invalid JSON. Re-import the original preset.",
    "invalid-profile-structure": "The native profile structure exceeds the supported worker limits.",
    "validation-error": "The worker rejected an input or generated result. Check model and profile integrity.",
    "engine-exited": (
        "OrcaSlicer exited without a recognised diagnostic. "
        "Review the isolated worker logs and confirm the selected printer, filament and process presets."
    ),
}


def explain_worker_failure(reason, status_code):
    """Return one safe user message for an exact worker reason/status."""
    if reason in REASONS:
        return REASONS[reason]
    if status_code == 422:
        return "The slicer worker rejected the job. Review its logs and the selected native presets."
    return "The slicer worker could not complete this job. Check its availability and logs."
