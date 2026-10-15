from __future__ import annotations

import json
from pathlib import Path

from cross_embodiment.cli import main
from tests.unit.test_package_lifecycle import _instance, _package


def _run_json(capsys, *arguments: str):
    assert main(list(arguments)) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return json.loads(output.out)


def test_package_cli_runs_complete_offline_lifecycle_without_importing_backend(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    source = _package(tmp_path / "source")
    artifact = tmp_path / "arm.cepack"
    store = tmp_path / "store"
    marker = tmp_path / "backend-imported"
    monkeypatch.setenv("EXAMPLE_BACKEND_IMPORT_MARKER", str(marker))

    built = _run_json(
        capsys,
        "package", "build", "--package-root", str(source),
        "--output", str(artifact), "--json",
    )
    assert built["package"]["name"] == "example/arm"
    installed = _run_json(
        capsys,
        "package", "install", "--artifact", str(artifact),
        "--store", str(store), "--json",
    )
    assert installed["package"]["version"] == "1.2.3"
    listed = _run_json(capsys, "package", "list", "--store", str(store), "--json")
    assert [(item["package"]["name"], item["package"]["version"]) for item in listed] == [
        ("example/arm", "1.2.3")
    ]
    inspected = _run_json(
        capsys, "package", "inspect", "example/arm@1.2.3",
        "--store", str(store), "--json",
    )
    assert inspected["package"]["tree_digest"] == installed["package"]["tree_digest"]
    activated = _run_json(
        capsys,
        "package", "activate", "example/arm@1.2.3",
        "--instance", str(_instance(tmp_path / "instance.yaml")),
        "--store", str(store), "--json",
    )
    assert activated["instance_id"] == "lab/arm01"
    use = _run_json(
        capsys, "package", "use", "--instance", "lab/arm01",
        "--store", str(store), "--json",
    )
    assert use["hardware_connected"] is False
    assert use["backend_entrypoint"] == "example_vendor.backend:Adapter"
    assert not marker.exists()

    assert main([
        "package", "uninstall", "example/arm@1.2.3", "--store", str(store), "--json",
    ]) == 2
    assert "active" in capsys.readouterr().err

    deactivated = _run_json(
        capsys, "package", "deactivate", "--instance", "lab/arm01",
        "--store", str(store), "--json",
    )
    assert deactivated == {"deactivated": "lab/arm01", "hardware_connected": False}
    removed = _run_json(
        capsys,
        "package", "uninstall", "example/arm@1.2.3",
        "--store", str(store), "--json",
    )
    assert removed["package_name"] == "example/arm"
    assert not marker.exists()
