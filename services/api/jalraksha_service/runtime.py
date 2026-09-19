"""
Where this service is running from: a source checkout, or a frozen desktop build.

WHY THIS EXISTS
---------------
The service used to assume it always ran from the repository, in three ways
that a PyInstaller build of the Windows desktop app breaks:

  * ``Path(__file__).resolve().parents[3]`` was treated as the repo root, to
    find ``paraview/render_static.py`` and ``tools/paraview/reservoir.py`` and
    as the working directory of child processes. Frozen, ``__file__`` sits
    under the bundle's ``_internal`` directory and three parents up is outside
    the install entirely.
  * Child processes were started as ``sys.executable -m <module>`` and
    ``sys.executable -c <code>``. Frozen, ``sys.executable`` is the backend exe,
    which does not understand ``-m`` or ``-c``; it understands the subcommands
    defined in ``desktop/backend/jalraksha_backend.py``.
  * A child's ``PYTHONPATH`` was pointed at the checkout. Frozen, there is no
    checkout, and the bundle carries its own import path.

Every such decision now goes through this module, so the source-checkout
behaviour is unchanged (the functions return exactly what the old inline code
built) and the frozen behaviour is defined in one place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

#: Subcommand names understood by the frozen backend exe. Kept here, beside the
#: argv builders that use them, so the entry point and its callers cannot drift.
FROZEN_SERVE = "serve"
FROZEN_RUN_WORKER = "run-worker"
FROZEN_PROBE = "probe-backends"


def is_frozen() -> bool:
    """True inside a PyInstaller (or similar) frozen build."""
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    """The source checkout this module lives in (meaningless when frozen)."""
    return Path(__file__).resolve().parents[3]


def resource_root() -> Path:
    """
    Root that ``paraview/`` and ``tools/paraview/`` are resolved against.

    The repository in a checkout; the bundle's data directory when frozen,
    where the PyInstaller spec places those two script trees at the same
    relative paths.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return repo_root()


def subprocess_cwd() -> Path:
    """
    Working directory for child processes.

    The repo root in a checkout, because stored export paths are relative to it.
    Frozen, the desktop shell starts the backend in the user's data root
    (``%LOCALAPPDATA%\\JalRaksha``) and children must inherit that, never the
    read-only install directory.
    """
    return Path.cwd() if is_frozen() else repo_root()


def child_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Environment for a child Python process.

    In a checkout the child needs both the service package and the library on
    its path. Frozen, the exe carries its own path and a PYTHONPATH pointing at
    a checkout that is not there would only invite a stray import.
    """
    env = dict(os.environ if base is None else base)
    if not is_frozen():
        root = repo_root()
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(root / "services" / "api"), str(root),
                          env.get("PYTHONPATH", "")]))
    return env


def worker_argv(payload_path: str) -> List[str]:
    """Command line that runs one simulation from a payload file."""
    if is_frozen():
        return [sys.executable, FROZEN_RUN_WORKER, payload_path]
    return [sys.executable, "-m", "jalraksha_service.run_worker", payload_path]


def probe_argv() -> List[str]:
    """Command line that prints the GPU-capability probe as one JSON line."""
    if is_frozen():
        return [sys.executable, FROZEN_PROBE]
    return [sys.executable, "-m", "jalraksha_service.backend_probe"]
