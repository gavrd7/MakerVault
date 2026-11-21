import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.headless_env import slicing_environment


class HeadlessSlicerEnvironmentTests(TestCase):
    def test_headless_qt_is_set_without_leaking_host_display_proxy_or_secrets(self):
        with TemporaryDirectory() as temp:
            with patch.dict(os.environ, {
                "DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-0",
                "HTTPS_PROXY": "http://host-proxy", "AWS_SECRET_ACCESS_KEY": "private",
                "LD_PRELOAD": "/tmp/host-library.so",
            }):
                environment = slicing_environment(Path(temp))
        self.assertEqual(environment["QT_QPA_PLATFORM"], "offscreen")
        self.assertEqual(environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(environment["APPIMAGE_EXTRACT_AND_RUN"], "1")
        self.assertEqual(environment["HOME"], temp)
        for unsafe in ("DISPLAY", "WAYLAND_DISPLAY", "HTTPS_PROXY",
                       "AWS_SECRET_ACCESS_KEY", "LD_PRELOAD"):
            self.assertNotIn(unsafe, environment)
        self.assertEqual(set(environment), {
            "HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
            "LANG", "LC_ALL", "PATH", "QT_QPA_PLATFORM", "QT_OPENGL",
            "LIBGL_ALWAYS_SOFTWARE", "NO_AT_BRIDGE", "APPIMAGE_EXTRACT_AND_RUN",
        })
