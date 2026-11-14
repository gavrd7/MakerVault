"""Fixed, no-network GUI runtime environment for CLI-capable slicer engines.

Orca and Creality Print depend on Qt even when invoked with command-line
slicing flags. The worker must provide a headless Qt environment rather than
inheriting DISPLAY, secrets, network proxy variables or host user settings.
This is an initial offscreen runtime; each exact engine release still needs a
real fixture acceptance test.
"""
from pathlib import Path


def slicing_environment(workdir: Path) -> dict[str, str]:
    root = str(Path(workdir).resolve(strict=True))
    return {
        "HOME": root,
        "TMPDIR": root,
        "XDG_CONFIG_HOME": root,
        "XDG_CACHE_HOME": root,
        "XDG_RUNTIME_DIR": root,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_OPENGL": "software",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "NO_AT_BRIDGE": "1",
        # A verified official AppImage can run without /dev/fuse in a
        # non-privileged, container-restricted environment.
        "APPIMAGE_EXTRACT_AND_RUN": "1",
    }
