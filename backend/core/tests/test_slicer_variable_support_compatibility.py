"""Orca tree/organic support incompatibility with non-default layer ranges."""
import json
from django.test import SimpleTestCase

from core.slicer_variable_layers import validate_orca_variable_support_compatibility


class OrcaVariableSupportCompatibilityTests(SimpleTestCase):
    def check(self, *, enabled="0", kind="normal(auto)", style="default", variable=True):
        process = {"enable_support": enabled, "support_type": kind, "support_style": style}
        raw = json.dumps(process).encode()
        validate_orca_variable_support_compatibility(raw, variable)
        return process

    def test_base_profile_without_supports_is_allowed(self):
        self.check()

    def test_normal_manual_support_paint_is_allowed(self):
        self.check(enabled="1", kind="normal(manual)")

    def test_normal_auto_supports_are_allowed(self):
        self.check(enabled="1")

    def test_tree_supports_without_variable_heights_are_untouched(self):
        self.check(enabled="1", kind="tree(auto)", variable=False)

    def test_tree_supports_are_rejected_when_variable_enabled(self):
        with self.assertRaisesRegex(ValueError, "normal/manual"):
            self.check(enabled="1", kind="tree(auto)")

    def test_organic_style_is_rejected_when_supports_enabled(self):
        with self.assertRaisesRegex(ValueError, "tree/organic"):
            self.check(enabled="1", kind="normal(manual)", style="organic")

    def test_disabled_tree_supports_are_safe(self):
        self.check(enabled="0", kind="tree(auto)", style="organic")
