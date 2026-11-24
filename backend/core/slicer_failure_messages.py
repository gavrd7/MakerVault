"""Safe, bounded explanations of isolated slicer worker failures.

Worker reasons are stable allowlisted categories, not arbitrary output text.
CLI exit statuses differ across Orca/Bambu versions. Never treat an exit code
alone as a definitive diagnosis, and never echo untrusted CLI output.
"""

REASONS = {
    "creality-profile-json-invalid": (
        "Creality Print rejected an invalid native JSON profile. Check the imported printer, filament and process presets."
    ),
    "creality-profile-parent-unresolved": (
        "A Creality Print preset still has an unresolved parent. Import its complete native dependency chain."
    ),
    "creality-profile-structure-invalid": (
        "Creality Print rejected an oversized or overly nested native preset."
    ),
    "creality-post-processing-blocked": (
        "The Creality Print preset contains a post-processing command that cannot run inside the isolated slicer worker."
    ),
    "creality-engine-unavailable": (
        "The Creality Print executable is unavailable inside the worker. Check the installed engine status."
    ),
    "creality-output-path-conflict": (
        "The isolated Creality Print output folder could not be prepared."
    ),
    "creality-cli-timeout": (
        "Creality Print's native CLI did not finish slicing within the allowed time."
    ),
    "creality-qt-platform-failed": ("Creality Print could not initialise its headless Qt platform in the slicer worker."),
    "creality-runtime-library-missing": ("Creality Print could not load a required runtime library inside the worker container."),
    "creality-cli-command-conflict": ("Creality Print rejected the CLI request because it detected conflicting commands in the supplied arguments."),
    "creality-cli-command-missing": ("Creality Print did not recognise a slicing action in the supplied command."),
    "creality-cli-parameters-invalid": ("Creality Print 7.3.1 returned its native invalid-parameters status (-2 / Linux 254). The command supplied by MakerVault requires investigation; this does not establish a profile mismatch."),
    "creality-cli-option-invalid": ("Creality Print rejected an option passed by MakerVault's CLI adapter."),
    "creality-native-preset-invalid": ("Creality Print could not load a native printer, filament or process preset."),
    "creality-native-project-invalid": ("Creality Print rejected the embedded native 3MF printer, filament or process configuration. The saved model positions were not changed; this requires correction of the Creality project adapter."),
    "creality-project-version-unsupported": ("Creality Print rejected the 3MF generator file version (native CLI -24). This is a MakerVault project metadata compatibility issue, not evidence that the selected filament presets are wrong."),
    "creality-cli-validation-error": ("Creality Print rejected the native 3MF slicing parameters during validation. This points to the embedded project configuration, not necessarily the selected filament profiles. The exit code does not identify the individual offending setting."),
    "creality-cli-exited": (
        "Creality Print started but exited before completing the slice. The exit status alone cannot identify whether the cause is a runtime problem, CLI option or native preset. Check the worker diagnostics."
    ),
    "creality-no-output-directory": (
        "Creality Print exited without creating the expected slicing output directory."
    ),
    "creality-unexpected-output-layout": (
        "Creality Print produced files in an unexpected layout rather than one supported G-code output."
    ),
    "creality-missing-gcode": (
        "Creality Print generated no usable G-code, or its output exceeded the size limit."
    ),
    "creality-launch-failed": (
        "The isolated worker could not launch the installed Creality Print binary."
    ),
    "native-line-width-invalid": (
        "OrcaSlicer rejected an effective extrusion line width as too small. "
        "Review the nozzle, process layer height and line-width settings; "
        "a CLI profile merge can differ from desktop slicing."
    ),
    "cli-print-validation-exit-205": (
        "OrcaSlicer exited with code 205 during slicing. This has been observed "
        "for print validation errors, but the specific rejected setting was "
        "not identified. Compare an unchanged STL with the same native presets."
    ),
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
    "native-tool-use-mismatch": (
        "The 3MF colour painting and model base assignment do not use two distinct "
        "native tools. Review the painted colour-to-slot mappings and base filament."
    ),
    "native-paint-tool-out-of-range": (
        "A painted region refers to a native tool outside the supplied filament palette."
    ),
    "native-paint-channel-conflict": (
        "The 3MF combines native colour and other facet-paint attributes in a way "
        "the isolated worker has not yet validated."
    ),
    "native-object-tool-invalid": (
        "A 3MF model specifies an extruder outside the validated filament palette."
    ),
    "native-object-tool-missing": (
        "The multi-material 3MF is missing an explicit native extruder assignment."
    ),
    "native-filament-palette-mismatch": (
        "The native filament presets do not match the 3MF tool order. "
        "Check the mapped CFS slots and assigned profiles."
    ),
    "native-object-settings-invalid": (
        "The generated 3MF contains an unsupported or invalid per-object slicer setting."
    ),
    "native-plate-instance-invalid": (
        "The 3MF contains an invalid native plate instance mapping."
    ),
    "native-multimaterial-variable-layers-unsupported": (
        "The saved project combines native multi-colour tools with variable "
        "layer-height ranges. This combination is not yet accepted by the "
        "isolated worker. Both edits remain preserved in the draft."
    ),
    "invalid-native-layer-ranges": (
        "The native variable-layer metadata failed validation. Review the "
        "saved height bands and the selected model."
    ),
    "invalid-native-plate": (
        "The generated 3MF plate membership or native plate metadata failed validation."
    ),
    "invalid-job-payload": "The worker rejected the slicing request envelope before inspecting its model.",
    "unsupported-input-format": "The worker did not accept the supplied model format.",
    "input-size-invalid": "A model or native profile exceeds the isolated worker input limit.",
    "input-encoding-invalid": "A model or native profile was not validly encoded for the worker.",
    "native-palette-contract-invalid": (
        "The isolated worker did not receive a valid Orca multi-material 3MF request "
        "with two to sixteen native filament presets."
    ),
    "native-palette-entry-invalid": (
        "One of the native filament presets in the multi-material palette is missing "
        "or is not a correctly encoded profile entry."
    ),
    "native-palette-encoding-invalid": (
        "A native filament preset in the multi-material palette has invalid transport encoding."
    ),
    "native-palette-size-invalid": (
        "A native filament preset in the multi-material palette is empty or exceeds the worker size limit."
    ),
    "native-gcode-tools-missing": (
        "The native slice did not contain tool selections and deposited extrusion "
        "for every assigned base or painted filament. Review the generated "
        "multi-material tool routing before printer submission."
    ),
    "validation-error": "The worker rejected an input or generated result. Check model and profile integrity.",
    "bambu-cli-aborted": (
        "Bambu Studio launched but aborted with SIGABRT during native slicing. "
        "The project, profile compatibility and slicer runtime require further verification; "
        "this is not an executable-permissions failure."
    ),
    "bambu-runtime-exit-126": (
        "Bambu Studio could not execute a required runtime command (exit 126). "
        "Check executable permissions, mount options and bundled runtime dependencies "
        "inside the isolated slicer worker. This does not establish a model or preset error."
    ),
    "bambu-cli-exited": (
        "Bambu Studio exited without producing a completed slice. "
        "The worker confirmed a CLI failure, but has not established whether "
        "the native project, selected profiles or engine runtime caused it."
    ),
    "creality-region-archive-invalid": (
        "Creality Print's generated native modifier archive failed worker admission "
        "before the slicer was launched. Check the Creality 3MF packaging adapter."
    ),
    "creality-region-graph-invalid": (
        "The generated Creality native 3MF has a component or external mesh mapping "
        "that the worker could not validate. The slicer binary was not launched."
    ),
    "creality-region-parts-invalid": (
        "The generated Creality 3MF's printable/modifier/negative part mapping "
        "failed strict validation. Inspect the native region adapter."
    ),
    "creality-region-metadata-invalid": (
        "The generated Creality 3MF's native part or plate metadata was rejected "
        "before the slicer binary could run."
    ),
    "creality-region-profiles-invalid": (
        "The Creality native modifier project contains an invalid embedded profile "
        "vector or project settings structure. Inspect MakerVault's wrapper."
    ),
    "engine-exited": (
        "The selected slicer exited without a recognised diagnostic. "
        "Review the isolated worker logs and native printer, filament and process compatibility."
    ),
}


def explain_worker_failure(reason, status_code):
    """Return one safe user message for an exact worker reason/status."""
    if reason in REASONS:
        return REASONS[reason]
    if status_code == 422:
        return "The slicer worker rejected the job. Review its logs and the selected native presets."
    return "The slicer worker could not complete this job. Check its availability and logs."
