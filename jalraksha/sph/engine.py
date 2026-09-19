"""
Which SPH engine runs the near-field case (Phase 7).

Two engines produce the same result contract:

  * "dualsphysics" — DualSPHysics v5.4 in native CUDA (dualsphysics_runner.py).
    The default whenever an install is found, because it is the engine whose
    GPU path actually does the work on the GPU.
  * "pysph"        — PySPH's WCSPHScheme (pysph_runner.py). Kept as the
    reference engine and as the fallback for machines without DualSPHysics.
    Its GPU path is host-bound (docs/validation_findings.md §12).

JALRAKSHA_SPH_ENGINE selects one explicitly. An explicit engine that cannot run
RAISES — asking for one engine and silently getting the other would make every
label and timing downstream untrue. "auto" (the default) picks DualSPHysics if
installed, else PySPH if importable, and records which and why in
`sph_engine` / `sph_engine_reason` on the result.

The hardware choice is separate and engine-specific (see each runner's
backend resolver); `sph_backend_for_solver` maps the run's single compute
control onto whichever engine resolves.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from jalraksha.sph.geometry import SPHUnavailableError

SPH_ENGINE_ENV = "JALRAKSHA_SPH_ENGINE"
ENGINES = ("dualsphysics", "pysph")


def resolve_sph_engine(requested: Optional[str] = None) -> Dict[str, str]:
    """
    Decide the SPH engine.

    Returns:
        {"engine": "dualsphysics" | "pysph", "reason": str}

    Raises:
        ValueError: unknown engine name.
        SPHUnavailableError: an explicitly requested engine cannot run, or no
            engine can run at all.
    """
    from jalraksha.sph.dualsphysics_runner import is_dualsphysics_available
    from jalraksha.sph.pysph_runner import is_pysph_available

    choice = (requested or os.environ.get(SPH_ENGINE_ENV, "") or "auto").strip().lower()
    if choice not in ("auto",) + ENGINES:
        raise ValueError(f"SPH engine must be auto, dualsphysics or pysph (got {choice!r})")

    if choice == "dualsphysics":
        ok, detail = is_dualsphysics_available()
        if not ok:
            raise SPHUnavailableError(f"DualSPHysics requested but unavailable: {detail}")
        return {"engine": "dualsphysics", "reason": f"DualSPHysics requested ({detail})"}
    if choice == "pysph":
        ok, detail = is_pysph_available()
        if not ok:
            raise SPHUnavailableError(f"PySPH requested but unavailable: {detail}")
        return {"engine": "pysph", "reason": f"PySPH requested ({detail})"}

    dsph_ok, dsph_detail = is_dualsphysics_available()
    if dsph_ok:
        return {"engine": "dualsphysics", "reason": dsph_detail}
    pysph_ok, pysph_detail = is_pysph_available()
    if pysph_ok:
        return {"engine": "pysph",
                "reason": f"DualSPHysics unavailable ({dsph_detail}); using {pysph_detail}"}
    raise SPHUnavailableError(
        f"No SPH engine can run here. DualSPHysics: {dsph_detail}. PySPH: {pysph_detail}."
    )


def sph_backend_for_solver(solver_backend: Optional[str]) -> str:
    """
    Map the run's compute backend ("auto" | "cuda" | "cpu") to an engine-neutral SPH one.

    "cuda" becomes the STRICT "gpu": a run that asked for the GPU only gets the
    GPU for BOTH solvers, exactly as the SWE ensemble re-raises rather than
    finishing on the CPU (solver/parallel.py). If the SPH GPU run cannot happen,
    tasks.py records "no SPH result" with the reason and the SWE products still
    publish; nothing is computed on the CPU in its place. main.py::submit_run
    refuses such a run up front when the probe already says SPH cannot use the GPU.

    "auto" keeps the fallback: GPU when it can run, else the CPU with the reason.
    Unknown names fall back to "auto" rather than raising, because the value
    already passed the API's validation.
    """
    choice = (solver_backend or "auto").strip().lower()
    if choice == "cuda":
        return "gpu"
    if choice in ("cpu", "auto"):
        return choice
    return "auto"


def _backend_for_engine(engine: str, backend: Optional[str]) -> Optional[str]:
    """Translate engine-neutral GPU spellings into what the chosen runner accepts."""
    if backend is None or engine == "dualsphysics":
        return backend
    return {"gpu": "opencl", "cuda": "opencl", "prefer_gpu": "prefer_opencl"}.get(
        backend.strip().lower(), backend
    )


def _module(engine: str):
    if engine == "dualsphysics":
        from jalraksha.sph import dualsphysics_runner

        return dualsphysics_runner
    from jalraksha.sph import pysph_runner

    return pysph_runner


def run_near_field_sph(*, engine: Optional[str] = None, backend: Optional[str] = "auto",
                       **kwargs: Any) -> Dict[str, Any]:
    """Run the near-field case on the resolved engine; the result names both engine and hardware."""
    chosen = resolve_sph_engine(engine)
    result = _module(chosen["engine"]).run_near_field_sph(
        backend=_backend_for_engine(chosen["engine"], backend), **kwargs
    )
    result["sph_engine"] = chosen["engine"]
    result["sph_engine_reason"] = chosen["reason"]
    return result


def run_still_water_validation(*, engine: Optional[str] = None, backend: Optional[str] = "auto",
                               **kwargs: Any) -> Dict[str, Any]:
    """The hydrostatic gate on the resolved engine."""
    chosen = resolve_sph_engine(engine)
    result = _module(chosen["engine"]).run_still_water_validation(
        backend=_backend_for_engine(chosen["engine"], backend), **kwargs
    )
    result["sph_engine"] = chosen["engine"]
    result["sph_engine_reason"] = chosen["reason"]
    return result


def probe_sph_gpu() -> Dict[str, Any]:
    """
    Whether near-field SPH CAN run on the GPU here, on the engine that would run.

    Returns {"available": bool, "reason": str, "engine": str | None}. Never raises.
    """
    try:
        chosen = resolve_sph_engine()
    except (SPHUnavailableError, ValueError) as exc:
        return {"available": False, "reason": str(exc), "engine": None}
    if chosen["engine"] == "dualsphysics":
        from jalraksha.sph.dualsphysics_runner import probe_dualsphysics_gpu

        ok, reason, _device = probe_dualsphysics_gpu()
        return {"available": bool(ok), "reason": reason, "engine": "dualsphysics"}
    from jalraksha.sph.pysph_runner import resolve_sph_backend

    # "prefer_opencl", not "auto": this asks whether the GPU CAN run SPH.
    choice = resolve_sph_backend("prefer_opencl")
    return {"available": choice["sph_backend"] != "cpu", "reason": choice["reason"], "engine": "pysph"}
