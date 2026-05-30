"""Entry point: run the Yonsei Portal MCP server over stdio."""
from __future__ import annotations

from .server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
