import unittest
from pathlib import Path


class DocsPolicyTests(unittest.TestCase):
    def test_outputs_contains_only_generated_artifacts(self):
        markdown = list(Path("outputs").glob("*.md"))
        self.assertEqual(markdown, [])

    def test_gitignore_documents_generated_output_policy(self):
        text = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("outputs/", text)

