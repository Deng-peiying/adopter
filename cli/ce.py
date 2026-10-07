#!/usr/bin/env python3
"""Run the source-checkout CLI without installing the project first."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cross_embodiment.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
