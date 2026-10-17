from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cross_embodiment.onboarding.catalog import load_capability_catalog


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "catalogs" / "capabilities" / "v0.1.yaml"


def test_shipped_catalog_freezes_v01_contract() -> None:
    catalog = load_capability_catalog(CATALOG)

    assert catalog.schema_version == "capability-catalog/v0.1"
    assert catalog.assessment_statuses == (
        "native",
        "derived",
        "unsupported",
        "unknown",
    )
    assert len(catalog.capabilities) == len({item.id for item in catalog.capabilities})
    assert catalog.get("joint_position_state").binding_operations == ("joint_state",)
    assert catalog.get("joint_position").binding_operations == ("joint_position",)
    assert catalog.get("ee_pose").binding_operations == ("cartesian_pose",)
    assert all(not item.required_for_profiles for item in catalog.capabilities)
    for item in catalog.capabilities:
        assert set(item.semantics) == {
            "kind",
            "input",
            "output",
            "units",
            "frame",
            "lifecycle",
        }


def _write_catalog(tmp_path: Path, transform) -> Path:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    transform(data)
    target = tmp_path / "catalog.yaml"
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def test_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = _write_catalog(
        tmp_path,
        lambda data: data["capabilities"].append(dict(data["capabilities"][0])),
    )
    with pytest.raises(ValueError, match="duplicate capability id"):
        load_capability_catalog(path)


def test_catalog_rejects_unknown_assessment_vocabulary(tmp_path: Path) -> None:
    path = _write_catalog(
        tmp_path,
        lambda data: data["assessment_statuses"].append("supported"),
    )
    with pytest.raises(ValueError, match="assessment_statuses"):
        load_capability_catalog(path)


def test_catalog_rejects_boolean_supported_substitute(tmp_path: Path) -> None:
    path = _write_catalog(
        tmp_path,
        lambda data: data["capabilities"][0].update({"supported": True}),
    )
    with pytest.raises(ValueError, match="unknown fields.*supported"):
        load_capability_catalog(path)


def test_catalog_rejects_missing_semantic_contract(tmp_path: Path) -> None:
    def remove_frame(data) -> None:
        del data["capabilities"][0]["semantics"]["frame"]

    path = _write_catalog(tmp_path, remove_frame)
    with pytest.raises(ValueError, match="semantic fields"):
        load_capability_catalog(path)


def test_catalog_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    path = _write_catalog(tmp_path, lambda data: data.update({"fallback": {}}))
    with pytest.raises(ValueError, match="unknown top-level fields"):
        load_capability_catalog(path)
