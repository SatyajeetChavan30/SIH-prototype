"""
The service must run both from a checkout and frozen inside the desktop app.

Pins four things the Windows desktop build depends on, each of which fails
silently or with a misleading error when it regresses:

- In a checkout, child processes start EXACTLY as before (``-m`` module form,
  repo-root cwd, PYTHONPATH on the checkout). Frozen, they start as the backend
  exe's subcommands, in the user's data root, with no PYTHONPATH.
- ``GET /capabilities`` offers ParaView only to a caller on the same machine,
  and only when paraview.exe, pvpython.exe and the render script all exist.
- ``POST /runs/{id}/open-paraview`` with pvpython missing answers with a reason
  instead of escaping as a bare 500 (it used to raise FileNotFoundError).
- ``FLOODVIEW_GEE_PROJECT`` still reaches Earth Engine, as config._env promised.

Nothing here launches ParaView, touches Earth Engine or compiles a kernel.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")
pytest.importorskip("fastapi", reason="FastAPI not installed")

from jalraksha_service import runtime  # noqa: E402


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """Pretend to be the PyInstaller build, with the bundle at tmp_path/bundle."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "jalraksha-backend.exe"))
    return bundle


class TestCheckoutBehaviourUnchanged:
    def test_not_frozen_in_tests(self):
        assert runtime.is_frozen() is False

    def test_worker_argv_is_the_module_form(self):
        assert runtime.worker_argv("p.json") == [
            sys.executable, "-m", "jalraksha_service.run_worker", "p.json"]

    def test_children_run_from_the_repo_root(self):
        assert runtime.subprocess_cwd() == REPO_ROOT
        assert runtime.resource_root() == REPO_ROOT

    def test_child_pythonpath_names_the_checkout(self):
        env = runtime.child_env({"PYTHONPATH": "extra"})
        parts = env["PYTHONPATH"].split(__import__("os").pathsep)
        assert parts == [str(REPO_ROOT / "services" / "api"), str(REPO_ROOT), "extra"]

    def test_paraview_script_resolves_in_the_checkout(self):
        from jalraksha_service import main

        assert main._paraview_script() == REPO_ROOT / "paraview" / "render_static.py"


class TestFrozenBehaviour:
    def test_worker_and_probe_use_subcommands(self, frozen):
        exe = str(frozen / "jalraksha-backend.exe")
        assert runtime.worker_argv("p.json") == [exe, runtime.FROZEN_RUN_WORKER, "p.json"]
        assert runtime.probe_argv() == [exe, runtime.FROZEN_PROBE]

    def test_resources_come_from_the_bundle_and_cwd_from_the_caller(
            self, frozen, tmp_path, monkeypatch):
        data_root = tmp_path / "localappdata"
        data_root.mkdir()
        monkeypatch.chdir(data_root)
        assert runtime.resource_root() == frozen
        assert runtime.subprocess_cwd() == data_root

    def test_no_pythonpath_is_invented(self, frozen):
        assert "PYTHONPATH" not in runtime.child_env({})


def test_probe_module_prints_the_same_payload_keys(monkeypatch):
    """The probe moved out of a -c string; its JSON contract must not change."""
    from jalraksha_service import backend_probe
    import jalraksha.solver.backend as backend
    import jalraksha.sph.pysph_runner as pysph_runner

    monkeypatch.setattr(backend, "cuda_probe", lambda: (False, "no GPU here", None))
    monkeypatch.setattr(pysph_runner, "resolve_sph_backend",
                        lambda req: {"sph_backend": "cpu", "reason": "cpu only"})
    answer = backend_probe.probe()
    # The reason may carry a note that numba-cuda is absent from this build.
    assert answer.pop("cuda_reason").startswith("no GPU here")
    assert answer == {
        "cuda_available": False, "cuda_device": None,
        "sph_gpu_available": False, "sph_gpu_reason": "cpu only",
    }


def test_probe_names_a_missing_numba_cuda(monkeypatch):
    """The CPU installer's probe must not blame a driver that is fine."""
    import importlib.util

    from jalraksha_service import backend_probe
    import jalraksha.solver.backend as backend
    import jalraksha.sph.pysph_runner as pysph_runner

    monkeypatch.setattr(backend, "cuda_probe",
                        lambda: (False, "numba.cuda found no usable CUDA driver or device", None))
    monkeypatch.setattr(pysph_runner, "resolve_sph_backend",
                        lambda req: {"sph_backend": "cpu", "reason": "cpu only"})
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "numba_cuda" else real_find_spec(name, *a))
    assert "numba-cuda is not installed in this build" in backend_probe.probe()["cuda_reason"]


def test_probe_module_runs_as_a_child_process():
    """What main.py actually executes in a checkout: argv, cwd and env together."""
    proc = subprocess.run(runtime.probe_argv(), capture_output=True, text=True,
                          timeout=300, cwd=str(runtime.subprocess_cwd()),
                          env=runtime.child_env())
    payload = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert set(json.loads(payload[-1])) == {
        "cuda_available", "cuda_reason", "cuda_device", "sph_gpu_available", "sph_gpu_reason"}


# ----------------------------------------------------------------------
# ParaView capability
# ----------------------------------------------------------------------


@pytest.fixture
def paraview_files(tmp_path, monkeypatch):
    from jalraksha_service import config

    exe = tmp_path / "paraview.exe"
    pvpython = tmp_path / "pvpython.exe"
    exe.write_text("")
    pvpython.write_text("")
    monkeypatch.setattr(config.settings, "PARAVIEW_EXE", str(exe))
    monkeypatch.setattr(config.settings, "PVPYTHON_EXE", str(pvpython))
    return exe, pvpython


def _request(host):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None)


class TestParaviewCapability:
    def test_available_locally_when_everything_exists(self, paraview_files):
        from jalraksha_service import main

        assert main.capabilities(_request("127.0.0.1"))["paraview_available"] is True

    @pytest.mark.parametrize("host", ["10.0.0.7", "192.168.1.20", None])
    def test_never_offered_to_a_remote_caller(self, paraview_files, host):
        from jalraksha_service import main

        answer = main.capabilities(_request(host))
        assert answer["paraview_available"] is False
        assert answer["paraview_reason"] == "not_local"

    def test_missing_gui(self, paraview_files):
        from jalraksha_service import main

        paraview_files[0].unlink()
        assert main.capabilities(_request("::1"))["paraview_reason"] == "paraview_not_found"

    def test_missing_pvpython(self, paraview_files):
        from jalraksha_service import main

        paraview_files[1].unlink()
        assert main.capabilities(_request("::1"))["paraview_reason"] == "pvpython_not_found"

    def test_missing_script_in_a_frozen_bundle(self, paraview_files, frozen):
        from jalraksha_service import main

        assert main.capabilities(_request("127.0.0.1"))["paraview_reason"] == "script_not_found"


def test_open_paraview_without_pvpython_is_a_reason_not_a_500(
        tmp_path, monkeypatch, paraview_files):
    """The defect: subprocess.run on a missing pvpython raised FileNotFoundError."""
    from jalraksha_service import config, db, main

    monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(config.settings, "DATA_DIR", tmp_path)
    db.init_db()
    run_id = db.create_run("tehri", {"name": "Tehri Dam"}, "swe")
    xdmf = tmp_path / "simulation" / f"{run_id}.xdmf"
    xdmf.parent.mkdir()
    xdmf.write_text("<Xdmf/>")
    db.insert_exports(run_id, [{"kind": "xdmf", "path_or_url": str(xdmf)}])
    db.update_run_status(run_id, "done", 100.0)
    paraview_files[1].unlink()

    answer = main.open_in_paraview(run_id, _request("127.0.0.1"))
    assert answer == {"launched": False, "reason": "pvpython_not_found",
                      "detail": answer["detail"]}


# ----------------------------------------------------------------------
# Earth Engine legacy project variable
# ----------------------------------------------------------------------


class TestGeeProjectEnv:
    def test_new_name_wins(self, monkeypatch):
        from jalraksha.gee import auth

        monkeypatch.setenv("JALRAKSHA_GEE_PROJECT", " new-project ")
        monkeypatch.setenv("FLOODVIEW_GEE_PROJECT", "old-project")
        assert auth.gee_project() == "new-project"

    def test_legacy_name_is_honoured(self, monkeypatch):
        from jalraksha.gee import auth

        monkeypatch.delenv("JALRAKSHA_GEE_PROJECT", raising=False)
        monkeypatch.setenv("FLOODVIEW_GEE_PROJECT", "old-project")
        assert auth.gee_project() == "old-project"

    def test_neither_set_is_empty(self, monkeypatch):
        from jalraksha.gee import auth

        monkeypatch.delenv("JALRAKSHA_GEE_PROJECT", raising=False)
        monkeypatch.delenv("FLOODVIEW_GEE_PROJECT", raising=False)
        assert auth.gee_project() == ""


def test_one_version_everywhere():
    """jalraksha.__version__ is the single source; the service reports it."""
    import jalraksha
    from jalraksha_service import main

    assert main.app.version == jalraksha.__version__
    for package_json in (REPO_ROOT / "frontend" / "package.json",
                         REPO_ROOT / "desktop" / "package.json"):
        if package_json.exists():
            assert json.loads(package_json.read_text())["version"] == jalraksha.__version__
