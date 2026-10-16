import tempfile
import unittest
from pathlib import Path

from cross_embodiment.package.project import load_project
from cross_embodiment.package.registry import LocalRegistry, _directory_digest
from cross_embodiment.errors import PackageError
from cross_embodiment.package.resolver import PackageResolver


PACKAGE = """
schema_version: hardware-package/v0.1
package: {name: example/arm, version: 1.2.3, vendor: Example, model: arm, type: robot}
embodiment_manifest: embodiment.yaml
backends: [{id: mock, type: mock}]
"""


class RegistryResolverTests(unittest.TestCase):
    def test_generated_root_log_symlinks_do_not_break_install_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.yaml").write_text(PACKAGE, encoding="utf-8")
            expected = _directory_digest(root)
            (root / "log").mkdir()
            (root / "log/latest").symlink_to("missing-generated-log")
            self.assertEqual(_directory_digest(root), expected)
            (root / "unexpected").symlink_to("package.yaml")
            with self.assertRaises(PackageError):
                _directory_digest(root)

    def test_resolves_project_from_catalog_and_writes_deterministic_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            package_dir = root / "packages" / "example" / "arm"
            package_dir.mkdir(parents=True)
            (package_dir / "package.yaml").write_text(PACKAGE, encoding="utf-8")
            (package_dir / "embodiment.yaml").write_text(
                "schema_version: embodiment/v0.2\nembodiment: {type: arm}\ndevices: []\n",
                encoding="utf-8",
            )
            (package_dir / "instance.yaml").write_text(
                """
schema_version: robot-instance/v0.1
instance: {id: lab/arm01}
robot: {package: example/arm, version: 1.2.3}
""",
                encoding="utf-8",
            )
            (root / "assets" / "catalog.yaml").write_text(
                """
packages:
  hardware:
    example/arm:
      version: 1.2.3
      path: packages/example/arm/package.yaml
""",
                encoding="utf-8",
            )
            project = root / "project.yaml"
            project.write_text(
                """
schema_version: project/v0.1
robots:
  arm: {package: example/arm, version: ^1.2, instance: packages/example/arm/instance.yaml}
runtime: {control_frequency_hz: 20}
""",
                encoding="utf-8",
            )

            registry = LocalRegistry(root)
            resolution = PackageResolver(registry).resolve(load_project(project))
            lock_a = resolution.to_lock()
            lock_b = PackageResolver(registry).resolve(load_project(project)).to_lock()

            self.assertEqual(lock_a.hardware, lock_b.hardware)
            self.assertEqual(lock_a.hardware["example/arm"]["version"], "1.2.3")
            self.assertTrue(lock_a.hardware["example/arm"]["digest"].startswith("sha256:"))

    def test_missing_package_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets/catalog.yaml").write_text("packages: {}\n", encoding="utf-8")
            project = root / "project.yaml"
            project.write_text(
                "schema_version: project/v0.1\nrobots: {arm: {package: missing/x, version: ^1}}\n",
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                PackageResolver(LocalRegistry(root)).resolve(load_project(project))


if __name__ == "__main__":
    unittest.main()
