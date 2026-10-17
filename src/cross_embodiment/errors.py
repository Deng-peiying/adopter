class CrossEmbodimentError(Exception):
    """Base SDK error."""


class CompatibilityError(CrossEmbodimentError):
    """Raised when a policy cannot safely run on a robot."""


class LifecycleError(CrossEmbodimentError):
    """Raised for invalid lifecycle transitions."""


class CommandRejected(CrossEmbodimentError):
    """Raised when a command violates the robot contract."""


class SafetyViolation(CrossEmbodimentError):
    """Raised when an action is unsafe."""


class PackageError(CrossEmbodimentError):
    """Raised when a hardware or policy package is invalid."""


class AssetError(PackageError):
    """Raised when an asset slot or variant cannot be resolved."""


class DependencyError(PackageError):
    """Raised when a backend or package dependency is unavailable."""


class DriverCrash(CrossEmbodimentError):
    """Raised when a managed driver exits unexpectedly."""
