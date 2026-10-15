from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any


_ALLOWED_SOURCES = {
    "operator_configured",
    "previously_live_validated_runtime_policy",
    "validated_test_policy",
}


@dataclass(frozen=True)
class RuntimeCompletionPolicy:
    timeout_s: float
    arrival_tolerance_rad: float
    settle_window_s: float
    source: str
    operator: str
    reference: str
    confirmed_at: str

    def validate(self) -> None:
        for name in (
            "timeout_s", "arrival_tolerance_rad", "settle_window_s",
        ):
            raw = getattr(self, name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.source not in _ALLOWED_SOURCES:
            raise ValueError(
                "source must be operator_configured, "
                "previously_live_validated_runtime_policy, or validated_test_policy"
            )
        for name in ("operator", "reference"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        try:
            parsed = datetime.fromisoformat(self.confirmed_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("confirmed_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("confirmed_at must include a timezone")

    def document(
        self,
        *,
        device_id: str,
        candidate_package_digest: str,
    ) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": "runtime-completion-policy/v0.1",
            "device_id": device_id,
            "capability_id": "joint_position",
            "timeout_s": float(self.timeout_s),
            "arrival_tolerance_rad": float(self.arrival_tolerance_rad),
            "settle_window_s": float(self.settle_window_s),
            "source": self.source,
            "operator": self.operator,
            "reference": self.reference,
            "confirmed_at": self.confirmed_at,
            "candidate_package_digest": candidate_package_digest,
            "evidence_boundary": (
                "operator runtime policy; not vendor-declared interface evidence"
            ),
        }
