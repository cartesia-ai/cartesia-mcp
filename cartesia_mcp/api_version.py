"""Shared Cartesia API version for all MCP HTTP calls."""

from __future__ import annotations

import os

# Latest stable version in docs (docs.json API Reference tab).
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2026-03-01")
