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
            "RobotBase.from_instance(",
            "allow_motion=False",
            "allow_motion=True",
            "target = dict(state.positions)",
            "RobotBase.from_instance()` 不会启动厂商 Driver",
            "robot.connect()` 不会使能机器人",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_readme_document_links_exist(self):
        import re

        text = Path("README.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\((docs/[^)#]+)(?:#[^)]*)?\)", text):
            self.assertTrue(Path(target).is_file(), target)

