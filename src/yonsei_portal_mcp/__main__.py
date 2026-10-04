"""Lazy command dispatch; no arguments preserves the MCP stdio server."""
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "doctor":
        from .doctor import main as doctor_main

        return doctor_main(args[1:])
    import os

    if os.environ.get("_YONSEI_DOCTOR_CHILD") == "1":
        # Older supported python-dotenv releases ignore PYTHON_DOTENV_DISABLED.
        # Suppress the loader before config imports it, in the disposable child
        # only. Normal stdio startup retains its original dotenv behavior.
        import dotenv

        dotenv.load_dotenv = lambda *args, **kwargs: False
    from .server import mcp

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
