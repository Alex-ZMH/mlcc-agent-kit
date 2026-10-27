"""Portable launcher for the installed MLCC Bundle MCP server."""

from __future__ import annotations

from pathlib import Path
import sys


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from mlcc.mcp_server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
