"""Verify the release always publishes a paired, digest-pinned slicer image.

This is a static contract test; it does not push GHCR images.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleaseImageContractTests(unittest.TestCase):
    def test_one_tag_workflow_publishes_slicer_then_main(self):
        workflow = (ROOT / ".github/workflows/publish-container.yml").read_text()
        self.assertIn('tags:\n      - "v*"', workflow)
        self.assertIn("slicer_worker/Dockerfile.generic", workflow)
        self.assertIn("ghcr.io/gavrd7/makervault-slicer:", workflow)
        self.assertIn("id: slicer", workflow)
        self.assertLess(
            workflow.index("name: Publish version-matched combined slicer image"),
            workflow.index("name: Build and publish multi-platform image"),
        )
        self.assertIn("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=${{ steps.slicer.outputs.digest }}", workflow)
        self.assertIn("MAKERVAULT_SLICER_WORKER_IMAGE=${{", workflow)
        self.assertIn("name: Verify released application embeds the matching slicer digest", workflow)
        self.assertFalse((ROOT / ".github/workflows/publish-combined-slicer.yml").exists())

    def test_published_app_defaults_to_release_pinned_slicer_identity(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn("ARG MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", dockerfile)
        self.assertIn("ARG MAKERVAULT_SLICER_WORKER_IMAGE", dockerfile)
        self.assertIn("ENV MAKERVAULT_SLICER_WORKER_IMAGE=", dockerfile)
        self.assertIn("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=", dockerfile)
        self.assertIn("ghcr.io/gavrd7/makervault-slicer:1.7.0", compose)
        self.assertNotIn("      MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST:", compose)
        self.assertNotIn("      MAKERVAULT_SLICER_WORKER_IMAGE:", compose)
        self.assertIn("slicer_worker.combined_service", compose)


if __name__ == "__main__":
    unittest.main()
