"""
CUDA backend: agreement with the CPU reference, and backend selection.

test_solver.py already runs every blocking gate and analytical test on both
backends, so the GPU is held to the physics on its own. This module adds the
second half: the GPU must also agree with the CPU on the same inputs.

The GPU is not bit-identical to the CPU, and these tests do not pretend it is.
NVVM fuses a*b + c into one rounding, and libdevice's pow can differ from the C
runtime's by an ulp (see flux_cuda.py). Measured, the difference is at
round-off: 1e-15 relative on h_max, identical step counts. The tolerances
below are about six orders of magnitude looser than that, so a real
divergence in a mirrored expression fails loudly, while round-off does not.
"""

import numpy as np
import pytest

from jalraksha.solver import backend as backend_module
from jalraksha.solver.backend import BackendUnavailableError, cuda_probe, resolve_backend
from jalraksha.solver.core import SWESolver
from jalraksha.solver.types import Grid, create_state

requires_cuda = pytest.mark.skipif(
    not cuda_probe()[0], reason=f"CUDA backend unavailable: {cuda_probe()[1]}"
)

# Relative agreement demanded of h_max between backends. Observed ~1e-15.
H_MAX_RTOL = 1e-9


def _ritter_case():
    nx = 200
    grid = Grid(nx=nx, ny=1, dx=0.5, dy=1.0, x0=-50.0)
    h_init = np.where(grid.cell_centres_x() < 0.0, 1.0, 0.0).reshape(1, nx)
    return grid, create_state(grid, h_init)


def _terrain_case():
    """
    2D dam-break over a sloping, rough bed with a spatially varying Manning field.

    A 10 m column of water, not a flat surface: the bed rises eastward, so the
    column slumps west and drains out through the transmissive west edge,
    fast enough to trip a low velocity cap. A flat-surface start would be a
    lake at rest, which never moves and would test nothing here.
    """
    rng = np.random.default_rng(3)
    ny, nx = 64, 80
    grid = Grid(nx=nx, ny=ny, dx=30.0, dy=30.0)
    yy, xx = np.mgrid[0:ny, 0:nx]
    bed = 0.05 * xx * 30.0 + 2.0 * np.sin(yy / 5.0) + rng.uniform(0, 0.5, (ny, nx))
    h_init = np.where(xx < 15, 10.0, 0.0)
    manning = rng.uniform(0.02, 0.08, (ny, nx))
    return grid, create_state(grid, h_init, b_init=bed), manning


@requires_cuda
class TestGpuMatchesCpu:
    def test_ritter_run(self):
        grid, state = _ritter_case()
        results = {
            name: SWESolver(grid, manning_n=0.0, cfl=0.9, backend=name).run(state, t_end=5.0)
            for name in ("cpu", "cuda")
        }
        cpu, gpu = results["cpu"], results["cuda"]
        assert cpu.n_steps == gpu.n_steps
        np.testing.assert_allclose(gpu.h_max, cpu.h_max, rtol=H_MAX_RTOL, atol=1e-12)
        np.testing.assert_allclose(gpu.state.h, cpu.state.h, rtol=H_MAX_RTOL, atol=1e-12)
        assert np.array_equal(np.isfinite(gpu.t_arrival), np.isfinite(cpu.t_arrival))

    def test_terrain_run_with_friction_field(self):
        grid, state, manning = _terrain_case()
        solvers = {
            name: SWESolver(grid, manning_n=manning, cfl=0.3, backend=name)
            for name in ("cpu", "cuda")
        }
        cpu = solvers["cpu"].run(state, t_end=600.0)
        gpu = solvers["cuda"].run(state, t_end=600.0)

        assert cpu.n_steps == gpu.n_steps
        np.testing.assert_allclose(gpu.h_max, cpu.h_max, rtol=H_MAX_RTOL, atol=1e-12)
        np.testing.assert_allclose(gpu.u_max, cpu.u_max, rtol=H_MAX_RTOL, atol=1e-10)
        # The same cells wet, at the same times to round-off. Bit-equality is the
        # wrong measure here: arrival time is the running sum of timesteps, and
        # each timestep differs between backends by an ulp. Measured: 99.8% of
        # cells bit-equal, the rest within 3.6e-15 s.
        assert np.array_equal(np.isfinite(gpu.t_arrival), np.isfinite(cpu.t_arrival))
        wet = np.isfinite(cpu.t_arrival)
        assert np.max(np.abs(gpu.t_arrival[wet] - cpu.t_arrival[wet])) < 1e-6
        assert abs(gpu.mass_error - cpu.mass_error) < 1e-12

    def test_velocity_cap_activations_are_counted_identically(self):
        """The cap is counted with an atomic add on the GPU; the count must match."""
        grid, state, manning = _terrain_case()
        counts = {}
        for name in ("cpu", "cuda"):
            solver = SWESolver(grid, manning_n=manning, cfl=0.3, velocity_max=2.0, backend=name)
            solver.run(state, t_end=120.0)
            counts[name] = solver.n_velocity_capped
        assert counts["cpu"] > 0, "test setup must make the cap fire"
        assert counts["cuda"] == counts["cpu"]

    def test_step_matches_run(self):
        """step() (upload/step/download) and run() (device-resident) are one physics."""
        grid, state = _ritter_case()
        stepped = SWESolver(grid, manning_n=0.0, cfl=0.9, backend="cuda")
        current = state.copy()
        for _ in range(50):
            current = stepped.step(current)

        reference = SWESolver(grid, manning_n=0.0, cfl=0.9, backend="cpu")
        expected = state.copy()
        for _ in range(50):
            expected = reference.step(expected)

        np.testing.assert_allclose(current.h, expected.h, rtol=H_MAX_RTOL, atol=1e-12)
        assert current.t == pytest.approx(expected.t, rel=1e-12)

    def test_outflow_is_accounted_on_the_device(self):
        """volume_exited_m3 must agree across backends on a draining domain."""
        grid, state, manning = _terrain_case()
        # Transmissive, and the bed falls to the west edge, so water leaves.
        exited = {}
        for name in ("cpu", "cuda"):
            solver = SWESolver(grid, manning_n=manning, cfl=0.3, backend=name)
            solver.run(state, t_end=1200.0)
            exited[name] = solver.volume_exited_m3
        assert exited["cpu"] > 0.0, "test setup must drain through the boundary"
        assert exited["cuda"] == pytest.approx(exited["cpu"], rel=1e-9)

    def test_describe_names_the_device(self):
        info = SWESolver(Grid(nx=4, ny=4, dx=1.0, dy=1.0), backend="cuda").describe()
        assert info["solver_backend"] == "cuda"
        assert info["precision"] == "float64"
        assert info["solver_device"]
        assert "GPU" in info["solver_backend_label"]


class TestBackendSelection:
    def test_cpu_request_is_honoured(self):
        assert resolve_backend("cpu").name == "cpu"

    def test_environment_variable_applies_to_auto(self, monkeypatch):
        monkeypatch.setenv(backend_module.ENV_VAR, "cpu")
        assert resolve_backend("auto").name == "cpu"
        assert resolve_backend(None).name == "cpu"

    def test_explicit_argument_beats_environment(self, monkeypatch):
        monkeypatch.setenv(backend_module.ENV_VAR, "cuda")
        assert resolve_backend("cpu").name == "cpu"

    def test_unknown_backend_is_rejected(self):
        with pytest.raises(ValueError):
            resolve_backend("tpu")

    def test_auto_falls_back_to_cpu_and_says_why(self, monkeypatch):
        monkeypatch.delenv(backend_module.ENV_VAR, raising=False)
        monkeypatch.setattr(backend_module, "cuda_probe", lambda: (False, "no driver here", None))
        choice = resolve_backend("auto")
        assert choice.name == "cpu"
        assert "no driver here" in choice.reason

    def test_explicit_cuda_request_raises_when_unavailable(self, monkeypatch):
        """Asked for the GPU and cannot have it: refuse rather than quietly run on the CPU."""
        monkeypatch.setattr(backend_module, "cuda_probe", lambda: (False, "no driver here", None))
        with pytest.raises(BackendUnavailableError, match="no driver here"):
            resolve_backend("cuda")
        with pytest.raises(BackendUnavailableError):
            SWESolver(Grid(nx=4, ny=4, dx=1.0, dy=1.0), backend="cuda")
