from __future__ import annotations

from pathlib import Path

import pytest

from cross_embodiment.onboarding.isolation import IsolationPolicy, PlatformLock


def test_policy_allows_vendor_and_platform_reads_and_staging_writes(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    platform = tmp_path / "platform"
    output = tmp_path / "staging"
    denied = tmp_path / "old-package"
    for path in (vendor, platform, output, denied):
        path.mkdir()
    source = vendor / "package.xml"
    source.write_text("<package/>")
    schema = platform / "schema.json"
    schema.write_text("{}")
    policy = IsolationPolicy((vendor,), (platform,), output, (denied,))

    assert policy.authorize_read(source) == source.resolve()
    assert policy.authorize_read(schema) == schema.resolve()
    assert policy.authorize_write(output / "hardware-package" / "package.yaml").is_relative_to(
        output.resolve()
    )


def test_policy_denies_old_answer_and_outside_paths(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    platform = tmp_path / "platform"
    output = tmp_path / "output"
    old = tmp_path / "ce-hardware-weiyi-dual-o6"
    for path in (vendor, platform, output, old):
        path.mkdir()
    policy = IsolationPolicy((vendor,), (platform,), output, (old,))

    with pytest.raises(PermissionError, match="denied"):
        policy.authorize_read(old / "config" / "mapping.yaml")
    with pytest.raises(PermissionError, match="allowed roots"):
        policy.authorize_read(Path("/etc/passwd"))
    with pytest.raises(PermissionError, match="staging output"):
        policy.authorize_write(vendor / "generated.yaml")


def test_policy_rejects_symlink_escape(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    output = tmp_path / "output"
    outside = tmp_path / "outside"
    platform = tmp_path / "platform"
    for path in (vendor, output, outside, platform):
        path.mkdir()
    (outside / "secret").write_text("secret")
    (vendor / "escape").symlink_to(outside, target_is_directory=True)
    policy = IsolationPolicy((vendor,), (platform,), output, ())

    with pytest.raises(PermissionError, match="allowed roots"):
        policy.authorize_read(vendor / "escape" / "secret")


def test_validate_generated_tree_rejects_symlinks(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    platform = tmp_path / "platform"
    output = tmp_path / "output"
    for path in (vendor, platform, output):
        path.mkdir()
    (output / "bad-link").symlink_to(vendor, target_is_directory=True)
    policy = IsolationPolicy((vendor,), (platform,), output, ())

    with pytest.raises(PermissionError, match="symlink"):
        policy.validate_generated_tree()


def test_platform_lock_captures_reproducible_environment(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = repo / "schemas" / "capability" / "catalog.schema.json"
    lock = PlatformLock.capture(repo, (schema,))
    path = tmp_path / "platform-lock.yaml"
    lock.write(path)

    assert len(lock.sdk_commit) == 40
    assert lock.python_version.startswith("3.10")
    assert lock.os_name
    assert lock.architecture
    assert lock.asset_digests[str(schema.relative_to(repo))]
    assert "sdk_commit:" in path.read_text(encoding="utf-8")
