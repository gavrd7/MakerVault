"""Publish extracted AppImage trees readable by the separate, unprivileged worker.

Called by the installer before making a version visible in the active manifest.
Never follow symlinks: the extracted upstream tree may contain links to bundled
libraries and AppRun itself can be a symlink. File contents/ownership are intact.
"""
import os
from pathlib import Path
import stat


def make_runtime_worker_readable(root, *, required_executables=()):
    """Allow read-only worker access; retain installer ownership and write policy."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid extracted engine runtime directory.")
    # Some official AppImages ship a shell AppRun whose internal binary has
    # no executable bit after extraction. Only named, reviewed engine
    # entrypoints may be explicitly granted execute permission. Reject
    # symlinks and traversal; never make arbitrary downloaded files executable.
    for relative in required_executables:
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise ValueError("Invalid reviewed runtime executable.")
        components = relative.split("/")
        if any(part in ("", ".", "..") for part in components):
            raise ValueError("Unsafe reviewed runtime executable path.")
        target = root
        for part in components:
            target = target / part
            if target.is_symlink():
                raise ValueError("Reviewed runtime executable cannot be a symlink.")
        if not target.is_file():
            raise ValueError("Reviewed runtime executable is missing.")
        mode = target.stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("Reviewed runtime executable must be a regular file.")
        # Retain installer ownership and do not alter user/group write bits.
        os.chmod(target, stat.S_IMODE(mode) | 0o111, follow_symlinks=False)
    for parent, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(parent)
        mode = base.stat(follow_symlinks=False).st_mode
        os.chmod(base, stat.S_IMODE(mode) | 0o055, follow_symlinks=False)
        for name in directories + filenames:
            entry = base / name
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if stat.S_ISDIR(mode):
                # os.walk will visit and fix it itself.
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("Unexpected non-file engine runtime entry.")
            # Preserve existing executable bits, never manufacture a new
            # executable, and never grant group/other write permissions.
            additional = 0o044 | (0o011 if mode & 0o111 else 0)
            os.chmod(entry, stat.S_IMODE(mode) | additional, follow_symlinks=False)
