import unittest
from pathlib import Path


class DocsPolicyTests(unittest.TestCase):
    def test_outputs_contains_only_generated_artifacts(self):
        markdown = list(Path("outputs").glob("*.md"))
        self.assertEqual(markdown, [])

    def test_gitignore_documents_generated_output_policy(self):
        text = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("outputs/", text)

    def test_readme_documents_installed_instance_python_runtime(self):
        text = Path("README.md").read_text(encoding="utf-8")
        for required in (
            "Robot.from_instance(",
            "allow_motion=False",
            "allow_motion=True",
            "target = dict(state.positions)",
            "Robot.from_instance()` 不会启动厂商 Driver",
            "robot.connect()` 不会使能机器人",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_runtime_docs_keep_driver_lifecycle_independent(self):
        package = Path("docs/package-lifecycle.md").read_text(encoding="utf-8")
        l3 = Path("docs/onboarding/installed-package-l3.md").read_text(encoding="utf-8")
        self.assertIn("Robot.from_instance()", package)
        self.assertIn("Driver Lifecycle", package)
        self.assertIn("shared installed Runtime loader", l3)
        self.assertIn("allow_motion=False", l3)

