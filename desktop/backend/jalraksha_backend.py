"""
Entry point of the frozen JalRaksha backend (jalraksha-backend.exe).

A frozen executable cannot be asked to run ``-m module`` or ``-c code``, so
every way the service starts a Python process is a subcommand here instead:

  serve --host 127.0.0.1 --port N   the FastAPI service (what the desktop app starts)
  run-worker <payload.json>         one simulation (main.py::_spawn_run_subprocess)
  probe-backends                    the GPU capability probe (main.py::_probe_cuda_out_of_process)
  pack import|export ...            data packs (jalraksha_service.data_packs)
  stop-active-runs [--list]         stop in-flight runs on desktop exit (jalraksha_service.run_control)
  diagnose                          print what decides GPU availability in this build (JSON)

jalraksha_service.runtime builds these command lines when frozen, and the
``-m`` forms from a checkout. The same script also runs unfrozen
(``python desktop/backend/jalraksha_backend.py <subcommand>``), which is how
the desktop app's development mode calls the CLI subcommands.

Nothing here changes what the service computes; it only decides how it starts.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def _prepare_environment() -> None:
    """Defaults the service needs before any of it is imported."""
    if not getattr(sys, "frozen", False):
        # Unfrozen: make the checkout importable, as scripts/run_api.py does.
        repo_root = Path(__file__).resolve().parents[2]
        for entry in (repo_root / "services" / "api", repo_root):
            if str(entry) not in sys.path:
                sys.path.insert(0, str(entry))

    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) / "JalRaksha" if local else Path.cwd()
    # No broker on the desktop: runs go to a detached subprocess (offline-first).
    os.environ.setdefault("CELERY_EAGER", "1")
    os.environ.setdefault("JALRAKSHA_DATA_DIR", "./data")
    # Numba writes compiled kernels next to their source by default — inside the
    # read-only install directory when frozen. The desktop shell always sets
    # this; the default covers a manual launch of the exe.
    os.environ.setdefault("NUMBA_CACHE_DIR", str(root / "cache" / "numba"))
    os.environ.setdefault("MPLCONFIGDIR", str(root / "cache" / "matplotlib"))


#: Import hooks that pip installs as ``.pth`` files. A frozen interpreter never
#: reads ``.pth`` files, so without this the GPU build silently imported numba's
#: legacy built-in ``numba.cuda`` instead of numba-cuda — measured: the frozen
#: probe answered "no usable CUDA driver or device" on a machine where the same
#: probe from a checkout found the RTX 4050. Absent in the CPU build; harmless.
PTH_IMPORT_HOOKS = ("_cuda_bindings_redirector", "_numba_cuda_redirector")


def _activate_pth_import_hooks() -> list[str]:
    activated = []
    for name in PTH_IMPORT_HOOKS:
        try:
            __import__(name)
            activated.append(name)
        except ImportError:
            pass
    return activated


def _diagnose() -> int:
    """Print the facts that decide GPU availability in THIS build, as JSON."""
    import json
    import platform

    facts: dict = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": platform.python_version(),
        "import_hooks": [n for n in PTH_IMPORT_HOOKS if n in sys.modules],
    }
    try:
        import numba

        facts["numba"] = numba.__version__
        from numba import cuda

        facts["numba_cuda_implementation"] = getattr(cuda, "implementation", None)
        facts["numba_cuda_module"] = getattr(cuda, "__file__", None)
        facts["cuda_is_available"] = bool(cuda.is_available())
        if not facts["cuda_is_available"]:
            try:
                facts["cuda_error"] = str(cuda.cuda_error())
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                facts["cuda_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        import traceback

        facts["numba_error"] = f"{type(exc).__name__}: {exc}"
        facts["numba_traceback"] = traceback.format_exc().splitlines()[-12:]
    try:
        from jalraksha_service import backend_probe

        facts["probe"] = backend_probe.probe()
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        facts["probe_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(facts, default=str))
    return 0


def _serve(args: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="jalraksha-backend serve")
    # Loopback only. The desktop app's API is for the window on this machine;
    # nothing in the shell ever needs it reachable from the network.
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost", "::1"])
    parser.add_argument("--port", type=int, required=True)
    opts = parser.parse_args(args)

    import uvicorn

    from jalraksha_service.main import app

    print(f"[backend] data dir   : {os.environ['JALRAKSHA_DATA_DIR']}", flush=True)
    print(f"[backend] cwd        : {os.getcwd()}", flush=True)
    print(f"[backend] numba cache: {os.environ['NUMBA_CACHE_DIR']}", flush=True)
    print(f"[backend] listening  : http://{opts.host}:{opts.port}", flush=True)
    uvicorn.run(app, host=opts.host, port=opts.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _prepare_environment()
    if getattr(sys, "frozen", False):
        _activate_pth_import_hooks()
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]

    if command == "serve":
        return _serve(rest)
    if command == "run-worker":
        from jalraksha_service import run_worker

        return run_worker.main(rest)
    if command == "probe-backends":
        from jalraksha_service import backend_probe

        return backend_probe.main()
    if command == "pack":
        from jalraksha_service import data_packs

        return data_packs.main(rest)
    if command == "stop-active-runs":
        from jalraksha_service import run_control

        return run_control.main(rest)
    if command == "diagnose":
        return _diagnose()
    print(f"unknown command {command!r}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    # FIRST, before anything else: the solver's ProcessPoolExecutor starts
    # children by re-running this executable, and freeze_support is what turns
    # such a child into a pool worker instead of a second backend.
    multiprocessing.freeze_support()
    sys.exit(main())
