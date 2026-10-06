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
