"""Small, dependency-free delivery trace written beside the project config."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def trace(message: str) -> None:
    """Print and append one diagnostic line without ever blocking game flow."""
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    try:
        with Path.cwd().joinpath("debug.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        # Console output remains available even if the current directory is read-only.
        print(f"[DEBUG LOG] write failed: {exc}", flush=True)
