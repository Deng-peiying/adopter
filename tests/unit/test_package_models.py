import tempfile
import unittest
from pathlib import Path

from cross_embodiment.errors import AssetError, DependencyError
from cross_embodiment.hardware.instance import load_robot_instance
from cross_embodiment.package.lock import load_lock
from cross_embodiment.package.manifest import PlatformInfo, load_package_manifest


PACKAGE_YAML = """
schema_version: hardware-package/v0.1
package:
  name: wy/dual_o6
  version: 1.0.0
  vendor: Weiyi
  model: dual_o6
  type: robot
embodiment_manifest: embodiment.yaml
assets:
  kinematic_model:
    - format: urdf
      path: assets/wy.urdf
      source: true
    - format: mjcf
      path: assets/wy.xml
      source: false
backends:
  - id: ros2_humble
    type: ros2
    launch: launch/dual.launch.py
    requirements:
      ros_distro: humble
  - id: mock
    type: mock
defaults:
  backend: ros2_humble
"""


class PackageModelTests(unittest.TestCase):
    def test_loads_asset_variants_and_selects_platform_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "package.yaml"
            path.write_text(PACKAGE_YAML, encoding="utf-8")
            package = load_package_manifest(path)

            self.assertEqual(package.name, "wy/dual_o6")
            self.assertEqual(package.resolve_asset("kinematic_model", "urdf").path, "assets/wy.urdf")
            backend = package.select_backend(
                None,
                PlatformInfo(os="linux", arch="amd64", ros_distro="humble"),
            )
            self.assertEqual(backend.id, "ros2_humble")

    def test_missing_asset_variant_is_typed_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.yaml"
            path.write_text(PACKAGE_YAML, encoding="utf-8")
            package = load_package_manifest(path)
            with self.assertRaises(AssetError):
                package.resolve_asset("kinematic_model", "usd")

    def test_instance_and_lock_load_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance_path = root / "instance.yaml"
            instance_path.write_text(
                """
schema_version: robot-instance/v0.1
instance:
  id: lab/wy01
robot:
  package: wy/dual_o6
  version: 1.0.0
backend:
  preferred: ros2_humble
connection:
  namespace: /wy_robot1
overrides:
  speed_limit: 0.2
""",
                encoding="utf-8",
            )
            lock_path = root / "embodiment.lock"
            lock_path.write_text(
                """
lock_version: v0.1
hardware:
  wy/dual_o6:
    version: 1.0.0
    digest: sha256:abc
""",
                encoding="utf-8",
            )
            instance = load_robot_instance(instance_path)
            lock = load_lock(lock_path)
            self.assertEqual(instance.instance_id, "lab/wy01")
            self.assertEqual(instance.overrides["speed_limit"], 0.2)
            self.assertEqual(lock.hardware["wy/dual_o6"]["digest"], "sha256:abc")

    def test_backend_requirement_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.yaml"
            path.write_text(PACKAGE_YAML, encoding="utf-8")
            package = load_package_manifest(path)
            with self.assertRaises(DependencyError):
                package.select_backend("ros2_humble", PlatformInfo(os="linux", arch="amd64", ros_distro="jazzy"))

    def test_manifest_rejects_unsupported_schema_and_missing_runtime_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "package.yaml"
            path.write_text(
                PACKAGE_YAML.replace("hardware-package/v0.1", "hardware-package/v9"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "schema_version"):
                load_package_manifest(path)

            path.write_text(
                """schema_version: hardware-package/v0.1
package: {name: example/arm, version: 1.0.0, vendor: Example, model: arm, type: robot}
backends: []
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "embodiment_manifest|Backend"):
                load_package_manifest(path)

if __name__ == "__main__":
    unittest.main()
