import builtins
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cross_embodiment
from cross_embodiment.errors import DependencyError
from cross_embodiment.package.manifest import load_package_manifest


HARDWARE_ROOT = Path(__file__).resolve().parents[1] / "fixtures/kinematics/two_joint_arm"


class OptionalKinematicsTests(unittest.TestCase):
    def test_core_sdk_import_does_not_load_optional_kinematics_dependencies(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, cross_embodiment; "
                "print(hasattr(cross_embodiment, 'Robot')); "
                "print('PyKDL' in sys.modules); "
                "print('urdf_parser_py' in sys.modules)",
            ],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        )

        self.assertEqual(result.stdout.splitlines(), ["True", "False", "False"])

    def test_requesting_missing_backend_reports_required_packages(self):
        from cross_embodiment.kinematics import load_kdl_chain

        package = load_package_manifest(HARDWARE_ROOT / "package.yaml")
        real_import = builtins.__import__

        def without_kdl(name, *args, **kwargs):
            if name == "PyKDL":
                raise ImportError("blocked for optional dependency test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_kdl):
            with self.assertRaisesRegex(DependencyError, "PyKDL.*python3-pykdl"):
                load_kdl_chain(package)


if __name__ == "__main__":
    unittest.main()
