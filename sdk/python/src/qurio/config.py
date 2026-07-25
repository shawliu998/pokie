"""Connection configuration shared by the Qurio SDK, CLI and MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class QurioConfigurationError(ValueError):
    """Raised when a Qurio connection cannot be configured safely."""


@dataclass(frozen=True, slots=True)
class QurioConnection:
    """A single authenticated Qurio workspace connection."""

    api_url: str
    workspace_id: str
    access_token: str

    def __post_init__(self) -> None:
        api_url = self.api_url.rstrip("/")
        parsed = urlsplit(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise QurioConfigurationError("QURIO_API_URL must be an absolute HTTP(S) URL.")
        if not self.workspace_id.strip():
            raise QurioConfigurationError("QURIO_WORKSPACE_ID is required.")
        if not self.access_token:
            raise QurioConfigurationError("QURIO_ACCESS_TOKEN is required.")
        object.__setattr__(self, "api_url", api_url)
        object.__setattr__(self, "workspace_id", self.workspace_id.strip())

    @classmethod
    def from_env(cls) -> QurioConnection:
        """Load the standard non-interactive Qurio connection environment."""

        return cls(
            api_url=os.environ.get("QURIO_API_URL", ""),
            workspace_id=os.environ.get("QURIO_WORKSPACE_ID", ""),
            access_token=os.environ.get("QURIO_ACCESS_TOKEN", ""),
        )
