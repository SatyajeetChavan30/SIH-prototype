"""
Compute-backend selection for the SWE solver: "cpu" (numba), "cuda" (numba-cuda).

The CPU numba kernels are the reference implementation and the fallback. The
CUDA backend runs the same physics (see flux_cuda.py) on an NVIDIA GPU.

Selection rules, in order:
  1. An explicit "cpu" or "cuda" argument wins.
  2. Otherwise ("auto" or None) the JALRAKSHA_SOLVER_BACKEND environment
     variable is read, defaulting to "auto".
  3. "auto" picks CUDA only if numba.cuda can see a device AND compile a
     float64 kernel on it, and falls back to CPU otherwise, recording why.
  4. An explicit "cuda" that cannot run RAISES. Silently running on the CPU
     after being asked for the GPU would make every timing and every
     provenance label a lie.

The probe result is cached per process. Importing numba.cuda and compiling
the probe kernel costs about a second, and the answer cannot change while the
process lives.
"""

import functools
import os
from dataclasses import dataclass
from typing import Optional, Tuple

BACKENDS = ("auto", "cpu", "cuda")
ENV_VAR = "JALRAKSHA_SOLVER_BACKEND"


class BackendUnavailableError(RuntimeError):
    """The CUDA backend was requested explicitly and cannot run here."""


@dataclass(frozen=True)
class BackendChoice:
    """The backend that will actually run, and why it was chosen."""

    name: str  # "cpu" or "cuda"
    requested: str  # what the caller or environment asked for
    reason: str
    device_name: Optional[str] = None

    @property
    def label(self) -> str:
        """Human-readable provenance, e.g. for the dashboard and run summaries."""
        if self.name == "cuda":
            return f"GPU (CUDA, {self.device_name}, float64)"
        return "CPU (numba, float64)"

    def as_dict(self) -> dict:
        return {
            "solver_backend": self.name,
            "solver_backend_requested": self.requested,
            "solver_backend_reason": self.reason,
            "solver_device": self.device_name,
            "solver_backend_label": self.label,
        }


@functools.lru_cache(maxsize=1)
def cuda_probe() -> Tuple[bool, str, Optional[str]]:
    """
    Can a float64 CUDA kernel compile and run here?

    Returns:
        (ok, detail, device_name)
    """
    try:
        import numpy as np
        from numba import cuda
    except Exception as exc:  # numba-cuda not installed
        return False, f"numba.cuda unavailable ({type(exc).__name__}: {exc})", None

    try:
        if not cuda.is_available():
            return False, "numba.cuda found no usable CUDA driver or device", None

        @cuda.jit
        def _probe(values):
            index = cuda.grid(1)
            if index < values.size:
                values[index] = values[index] * 2.0 + 1.0

        values = cuda.to_device(np.arange(4, dtype=np.float64))
        _probe[1, 4](values)
        if not np.array_equal(values.copy_to_host(), np.array([1.0, 3.0, 5.0, 7.0])):
            return False, "CUDA float64 probe kernel returned wrong values", None

        name = cuda.get_current_device().name
        if isinstance(name, bytes):
            name = name.decode()
        return True, f"CUDA device available: {name}", str(name)
    except Exception as exc:
        return False, f"CUDA probe failed ({type(exc).__name__}: {exc})", None


def resolve_backend(requested: Optional[str] = None) -> BackendChoice:
    """
    Decide which backend runs.

    Args:
        requested: "auto", "cpu", "cuda" or None (None behaves like "auto").

    Raises:
        ValueError: on an unknown backend name.
        BackendUnavailableError: if "cuda" was requested and cannot run.
    """
    if requested is None or str(requested).lower() == "auto":
        requested = os.environ.get(ENV_VAR, "auto")
    requested = str(requested).strip().lower()
    if requested not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS} (got {requested!r})")

    if requested == "cpu":
        return BackendChoice("cpu", requested, "CPU requested")

    ok, detail, device_name = cuda_probe()
    if ok:
        return BackendChoice("cuda", requested, detail, device_name)
    if requested == "cuda":
        raise BackendUnavailableError(f"CUDA backend requested but unavailable: {detail}")
    return BackendChoice("cpu", requested, f"CUDA unavailable, running on CPU: {detail}")
