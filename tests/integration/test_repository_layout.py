import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RepositoryLayoutTests(unittest.TestCase):
    def test_architecture_docs_live_under_docs_and_outputs_is_generated_only(self):
        self.assertTrue((ROOT / "docs/architecture/cross-embodiment-sdk-design-v0.2.md").is_file())
        self.assertTrue((ROOT / "docs/architecture/cross-embodiment-sdk-design-v0.1.md").is_file())
        doc_directories = {path.name for path in (ROOT / "docs").iterdir() if path.is_dir()}
        # Git does not retain an empty implementation directory in a clone.
        self.assertTrue(doc_directories <= {"architecture", "implementation"})
        output_docs = list((ROOT / "outputs").glob("*.md"))
        self.assertEqual([], output_docs)


if __name__ == "__main__":
    unittest.main()
