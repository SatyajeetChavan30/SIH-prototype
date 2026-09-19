"""
Print whether this machine can run the GPU backends, as one JSON line.

This used to be a ``python -c "<code>"`` string inside main.py. A frozen desktop
build has no ``-c``, so the same code lives here and runs either as
``python -m jalraksha_service.backend_probe`` or as the frozen exe's
``probe-backends`` subcommand. The payload keys are unchanged.

It runs OUT of the API process on purpose: compiling a CUDA kernel creates a
CUDA context, which would otherwise hold part of the card for the server's whole
life (see main.py::_probe_cuda_out_of_process).
"""

from __future__ import annotations

import json
from typing import Any, Dict


def probe() -> Dict[str, Any]:
    # Answers for BOTH engines, because they can disagree: the SWE solver needs
    # numba-cuda, the near-field SPH needs DualSPHysics's CUDA build (or, where
    # DualSPHysics is not installed, PySPH's OpenCL path).
    from jalraksha.solver.backend import cuda_probe
    from jalraksha.sph.engine import probe_sph_gpu

    ok, detail, device = cuda_probe()
    if not ok:
        from importlib.util import find_spec

        # numba ships a legacy numba.cuda that answers "no usable CUDA driver"
        # when numba-cuda (and its NVVM) is simply absent — as in the CPU desktop
        # installer — even on a machine whose driver is fine. Say which it is.
        if find_spec("numba_cuda") is None:
            detail = (f"{detail} — numba-cuda is not installed in this build "
                      f"(the CPU desktop installer does not bundle it)")
    # Asks whether the GPU CAN run SPH on the engine that would run, by running
    # it: DualSPHysics's GPU executable is started on a tiny tank.
    sph = probe_sph_gpu()
    return {
        "cuda_available": bool(ok),
        "cuda_reason": detail,
        "cuda_device": device,
        "sph_gpu_available": sph["available"],
        "sph_gpu_reason": sph["reason"],
    }


def main() -> int:
    print(json.dumps(probe()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
