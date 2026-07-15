"""
AIContext — scoped request context for the middleware demo.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AIContext:
    """Every middleware call carries this. Validated at the boundary."""

    tenant_id: str
    user_id: str
    session_id: str
    metadata: Optional[dict[str, Any]] = None

    def validate(self) -> None:
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("AIContext requires non-empty tenant_id")
        if not self.user_id or not self.user_id.strip():
            raise ValueError("AIContext requires non-empty user_id")
        if not self.session_id or not self.session_id.strip():
            raise ValueError("AIContext requires non-empty session_id")

    def matches(self, **kwargs) -> bool:
        """Used by tools to guard against cross-tenant reads."""
        if "tenant_id" in kwargs and kwargs["tenant_id"] != self.tenant_id:
            return False
        if "user_id" in kwargs and kwargs["user_id"] != self.user_id:
            return False
        return True
