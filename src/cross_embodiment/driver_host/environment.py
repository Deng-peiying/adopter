"""Describe a child environment without mutating the application's environment."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
from typing import Mapping


@dataclass(frozen=True)
class EnvironmentSpec:
    setup_scripts: tuple[Path, ...] = ()
    overrides: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if any(not Path(script).is_file() for script in self.setup_scripts):
            raise ValueError("A runtime environment setup script is missing")

    def resolve(self, *, timeout_s: float = 20.0) -> dict[str, str]:
        """Run only at connection time, in an independent shell."""
        env = dict(os.environ)
        env.update(self.overrides)
        if not self.setup_scripts:
            return env
        result = subprocess.run(
            ['bash', '--noprofile', '--norc', '-c',
             'for setup in "$@"; do source "$setup" >&2 || exit; done; env -0',
             'ce-environment', *(str(Path(p).resolve()) for p in self.setup_scripts)],
            env=env, stdout=subprocess.PIPE, check=True, timeout=timeout_s,
        )
        return dict(os.fsdecode(item).split('=', 1)
                    for item in result.stdout.split(b'\0') if b'=' in item)
