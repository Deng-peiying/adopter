"""Cross-embodiment SDK v0.1 public API."""

from .errors import (
    AssetError,
    CompatibilityError,
    CrossEmbodimentError,
    DependencyError,
    PackageError,
    SafetyViolation,
)
from .package.manifest import HardwarePackage, PlatformInfo, load_package_manifest
from .hardware.instance import RobotInstance, load_robot_instance
from .package.lock import EmbodimentLock, load_lock
from .package.project import ProjectSpec, load_project
from .package.registry import LocalRegistry
from .package.resolver import PackageResolver, Resolution
from .driver.health import HealthReport
from .runtime.safety import SafetyGuard
from .runtime.mapping import ActionMapper
from .hardware.manifest import EmbodimentManifest, load_manifest
from .runtime.runtime import Runtime
from .sdk.robot import Command, Robot, connect

__all__ = [
    "Command",
    "AssetError",
    "CompatibilityError",
    "CrossEmbodimentError",
    "DependencyError",
    "EmbodimentLock",
    "EmbodimentManifest",
    "Robot",
    "Runtime",
    "HardwarePackage",
    "HealthReport",
    "SafetyGuard",
    "ActionMapper",
    "PlatformInfo",
    "PackageResolver",
    "PackageError",
    "ProjectSpec",
    "Resolution",
    "RobotInstance",
    "SafetyViolation",
    "connect",
    "load_manifest",
    "load_package_manifest",
    "load_robot_instance",
    "load_lock",
    "load_project",
    "LocalRegistry",
]
