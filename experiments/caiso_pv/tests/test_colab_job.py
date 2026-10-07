"""Bundle guards on miniature zip fixtures; no dataset download or training."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from colab_formal_job import DATA_FILES, REQUIRED_SCRIPTS, stage_bundle, validate_bundle  # noqa: E402


class ColabBundleTests(unittest.TestCase):
    def test_new_bundle_extraction_measures_size_and_refuses_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            npz = directory / "fixture.npz"
            np.savez_compressed(npz, explicit_math_fixture=np.zeros((2, 3), np.float32))
            archive = directory / "bundle.zip"
            with zipfile.ZipFile(archive, "x") as bundle:
                for name in REQUIRED_SCRIPTS:
                    bundle.writestr(f"scripts/{name}", "# Bundle fixture; never executed\n")
                for name in DATA_FILES:
                    if name == "dataset.npz":
                        bundle.write(npz, "data/processed/math_fixture/dataset.npz")
                    else:
                        bundle.writestr(f"data/processed/math_fixture/{name}", json.dumps({"fixture": True}))
            workspace = directory / "fresh_workspace"
            inventory = stage_bundle(archive, workspace, "data/processed/math_fixture")
            self.assertGreater(inventory["dataset_npz_bytes"], 0)
            self.assertGreater(inventory["array_uncompressed_bytes"], inventory["array_compressed_bytes"])
            with self.assertRaises(FileExistsError):
                stage_bundle(archive, workspace, "data/processed/math_fixture")

    def test_traversal_production_assets_and_missing_assets_are_rejected(self):
        for member in ("../existing_model.keras", "models/production.keras", "frontend/app.tsx", "scripts/only.py"):
            with self.subTest(member=member), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "bad.zip"
                with zipfile.ZipFile(archive, "x") as bundle:
                    bundle.writestr(member, "fixture")
                with self.assertRaises(ValueError):
                    validate_bundle(archive, "data/processed/math_fixture")


if __name__ == "__main__":
    unittest.main()
