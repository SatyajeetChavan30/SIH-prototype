"""
Per-run size overrides for the durable script path.

scripts/run_khadakwasla_drainage_check.py takes a custom domain (--margins) and
a near-field SPH size (--sph-window-km / --sph-duration-s / --sph-particles),
which reach tasks._run_near_field_sph through dam_config. A margins typo
silently changes which gauges are in the grid, and an override that is accepted
but not forwarded silently runs the default size, so both are pinned here.
"""

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "run_khadakwasla_drainage_check", ROOT / "scripts" / "run_khadakwasla_drainage_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMargins:
    def test_four_values_become_a_margins_dict(self):
        script = _load_script()
        assert script.parse_margins("8,32,8,18") == {
            "west": 8.0, "east": 32.0, "south": 8.0, "north": 18.0}

    @pytest.mark.parametrize("bad", ["8,32,8", "8,32,8,18,1", "8,-1,8,18", "a,32,8,18", "0,0,8,18"])
    def test_malformed_margins_are_refused(self, bad):
        script = _load_script()
        with pytest.raises(argparse.ArgumentTypeError):
            script.parse_margins(bad)

    def test_flags_parse_and_defaults_stay_verbatim(self):
        script = _load_script()
        defaults = script.parse_args([])
        assert defaults.margins is None and defaults.backend == "auto"
        assert defaults.sph_particles is None and defaults.solver == "swe"
        args = script.parse_args(["--margins", "8,32,8,18", "--solver", "sph", "--backend", "cuda",
                                  "--sph-window-km", "1.5", "--sph-particles", "150000"])
        assert args.margins["east"] == 32.0 and args.solver == "sph"
        assert args.sph_window_km == 1.5 and args.sph_particles == 150000


def _tiny_dem(path, left, bottom, right, top):
    import rasterio
    from rasterio.transform import from_bounds

    data = np.ones((20, 20), dtype=np.float32)
    with rasterio.open(path, "w", driver="GTiff", height=20, width=20, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_bounds(left, bottom, right, top, 20, 20)) as dst:
        dst.write(data, 1)
    return path


class TestDemCoverage:
    DAM_LAT, DAM_LON = 18.4436, 73.7686

    def test_dem_flag_parses(self):
        script = _load_script()
        assert script.parse_args(["--dem", "wide.tif"]).dem == "wide.tif"
        assert script.parse_args([]).dem is None

    def test_a_dem_that_covers_the_domain_passes(self, tmp_path):
        script = _load_script()
        dem = _tiny_dem(tmp_path / "wide.tif", 73.0, 17.0, 75.0, 19.5)
        margins = {"west": 10, "east": 50, "south": 20, "north": 20}
        assert script.dem_margin_shortfall(dem, self.DAM_LAT, self.DAM_LON, margins) == []

    def test_a_domain_past_the_dem_edge_is_named(self, tmp_path):
        """The 500 x 400 km box on the 240 x 188 km cache must be refused, east edge named."""
        script = _load_script()
        dem = _tiny_dem(tmp_path / "cached.tif", 73.38875, 17.5967, 75.6679, 19.2906)
        big = {"west": 80, "east": 420, "south": 200, "north": 200}
        short = script.dem_margin_shortfall(dem, self.DAM_LAT, self.DAM_LON, big)
        assert len(short) == 4 and short[1].startswith("east")
        full = {"west": 40, "east": 200, "south": 94, "north": 94}
        assert script.dem_margin_shortfall(dem, self.DAM_LAT, self.DAM_LON, full) == []


def _stub_sph_inputs(monkeypatch, captured):
    from jalraksha.sph import engine
    from jalraksha.terrain import breach, conditioning
    from jalraksha_service import tasks

    monkeypatch.setattr(tasks, "_resolve_dem", lambda cfg: "dem.tif")

    def fake_load(dem_path, lat, lon, target_resolution, domain_radius_km):
        captured["domain_radius_km"] = domain_radius_km
        return None, np.zeros((4, 4))

    monkeypatch.setattr(conditioning, "load_dem_as_grid", fake_load)
    member = {"metadata": {"q_peak_m3_s": 1000.0, "breach_width_m": 40.0}}
    monkeypatch.setattr(breach, "synthesize_scenario_ensemble", lambda cfg, num_samples: [member])
    monkeypatch.setattr(breach, "ensemble_statistics", lambda h: {"q_peak_median": 1000.0})

    def fake_run(**kwargs):
        captured["run_kwargs"] = kwargs
        return {"engine": "fake"}

    monkeypatch.setattr(engine, "run_near_field_sph", fake_run)
    return tasks


def test_sph_size_overrides_reach_the_engine(monkeypatch):
    captured = {}
    tasks = _stub_sph_inputs(monkeypatch, captured)
    result, error = tasks._run_near_field_sph({
        "lat": 18.44, "lon": 73.77, "height_m": 39.6, "solver_backend": "cuda",
        "sph_window_radius_km": 1.5, "sph_duration_s": 20.0, "sph_target_particles": 150000})
    assert error is None
    assert captured["domain_radius_km"] == 1.5
    assert captured["run_kwargs"]["duration_s"] == 20.0
    assert captured["run_kwargs"]["target_particles"] == 150000
    assert captured["run_kwargs"]["backend"] == "gpu"
    assert result["sph_window_radius_km"] == 1.5 and result["sph_target_particles"] == 150000


def test_without_overrides_the_service_defaults_apply(monkeypatch):
    captured = {}
    tasks = _stub_sph_inputs(monkeypatch, captured)
    tasks._run_near_field_sph({"lat": 18.44, "lon": 73.77, "height_m": 39.6})
    assert captured["domain_radius_km"] == tasks.SPH_WINDOW_RADIUS_KM
    assert captured["run_kwargs"]["duration_s"] == tasks.SPH_DURATION_S
    # No budget passed, so each engine keeps its own default.
    assert "target_particles" not in captured["run_kwargs"]
