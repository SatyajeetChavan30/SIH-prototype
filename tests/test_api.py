"""
Phase 14 REST API Test Suite.

Tests:
  - TestHealthEndpoint: GET /health liveness check
  - TestDamsEndpoint: GET /api/v1/dams list
  - TestGaugesEndpoint: GET /api/v1/gauges with lat/lon params
  - TestSimulateEndpoint: POST /api/v1/simulate with valid/invalid body
  - TestGetDownstreamGauges: unit tests for gauge lookup function
  - TestRapidEstimate: unit tests for rapid analytic estimate
"""

import json
import threading
import urllib.request
import urllib.error
import pytest

from jalraksha.api import (
    start_api_server,
    stop_api_server,
    get_downstream_gauges,
    rapid_estimate,
    DEMO_DAMS,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_server():
    """Start API server on port 18502 for tests (avoids conflict with production)."""
    server = start_api_server(host="127.0.0.1", port=18502)
    yield server
    stop_api_server(server)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, data: dict) -> tuple:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


BASE = "http://127.0.0.1:18502"


# ─── TestHealthEndpoint ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self, api_server):
        data = get_json(f"{BASE}/health")
        assert data["status"] == "ok"

    def test_health_contains_service_name(self, api_server):
        data = get_json(f"{BASE}/health")
        assert "JalRaksha" in data["service"]


# ─── TestDamsEndpoint ─────────────────────────────────────────────────────────

class TestDamsEndpoint:
    def test_dams_returns_list(self, api_server):
        data = get_json(f"{BASE}/api/v1/dams")
        assert "dams" in data
        assert isinstance(data["dams"], list)

    def test_dams_contains_tehri(self, api_server):
        data = get_json(f"{BASE}/api/v1/dams")
        ids = [d["id"] for d in data["dams"]]
        assert "tehri" in ids

    def test_dams_have_required_fields(self, api_server):
        data = get_json(f"{BASE}/api/v1/dams")
        for dam in data["dams"]:
            assert "id" in dam
            assert "name" in dam
            assert "lat" in dam
            assert "lon" in dam
            assert "height_m" in dam


# ─── TestGaugesEndpoint ───────────────────────────────────────────────────────

class TestGaugesEndpoint:
    def test_tehri_gauges_returned(self, api_server):
        data = get_json(f"{BASE}/api/v1/gauges?lat=30.38&lon=78.48&dam_id=tehri")
        assert "gauges" in data
        names = [g["name"] for g in data["gauges"]]
        assert "Koteshwar" in names
        assert "Haridwar" in names

    def test_gauges_have_required_fields(self, api_server):
        data = get_json(f"{BASE}/api/v1/gauges?lat=30.38&lon=78.48")
        for gauge in data["gauges"]:
            assert "name" in gauge
            assert "distance_km" in gauge
            assert "lat" in gauge
            assert "lon" in gauge


# ─── TestSimulateEndpoint ─────────────────────────────────────────────────────

class TestSimulateEndpoint:
    @pytest.fixture
    def tehri_body(self):
        return {
            "name": "Tehri",
            "lat": 30.3789,
            "lon": 78.4789,
            "height_m": 260.0,
            "storage_mm3": 3540.0,
            "dam_type": "embankment",
            "failure_mode": "overtopping",
            "ensemble_size": 3,
        }

    def test_valid_request_returns_200(self, api_server, tehri_body):
        status, data = post_json(f"{BASE}/api/v1/simulate", tehri_body)
        assert status == 200

    def test_response_has_q_peak(self, api_server, tehri_body):
        _, data = post_json(f"{BASE}/api/v1/simulate", tehri_body)
        assert "q_peak_median_m3s" in data
        assert data["q_peak_median_m3s"] > 0

    def test_response_has_arrival_times(self, api_server, tehri_body):
        _, data = post_json(f"{BASE}/api/v1/simulate", tehri_body)
        assert "arrival_times" in data
        assert len(data["arrival_times"]) >= 1

    def test_missing_fields_returns_400(self, api_server):
        status, data = post_json(f"{BASE}/api/v1/simulate", {"name": "Test"})
        assert status == 400
        assert "error" in data

    def test_invalid_height_returns_422(self, api_server):
        bad_body = {
            "name": "Bad",
            "lat": 30.0, "lon": 78.0,
            "height_m": 999.0,
            "storage_mm3": 1000.0,
        }
        status, data = post_json(f"{BASE}/api/v1/simulate", bad_body)
        assert status == 422

    def test_unknown_post_endpoint_returns_404(self, api_server):
        status, data = post_json(f"{BASE}/api/v1/nonexistent", {})
        assert status == 404


# ─── TestGetDownstreamGauges ──────────────────────────────────────────────────

class TestGetDownstreamGauges:
    def test_tehri_id_returns_known_gauges(self):
        gauges = get_downstream_gauges(30.38, 78.48, dam_id="tehri")
        names = [g["name"] for g in gauges]
        assert "Koteshwar" in names
        assert "Rishikesh" in names

    def test_unknown_location_returns_generic_gauges(self):
        gauges = get_downstream_gauges(20.0, 70.0, dam_id=None)
        assert len(gauges) >= 2
        for g in gauges:
            assert "distance_km" in g

    def test_all_gauges_have_positive_distance(self):
        gauges = get_downstream_gauges(30.38, 78.48)
        for g in gauges:
            assert g["distance_km"] > 0


# ─── TestRapidEstimate ────────────────────────────────────────────────────────

class TestRapidEstimate:
    @pytest.fixture
    def tehri_config(self):
        return {
            "name": "Tehri",
            "lat": 30.38, "lon": 78.48,
            "height_m": 260.0, "storage_mm3": 3540.0,
            "dam_type": "embankment", "failure_mode": "overtopping",
        }

    def test_returns_positive_q_peak(self, tehri_config):
        result = rapid_estimate(tehri_config, ensemble_size=3)
        assert result["q_peak_median_m3s"] > 0

    def test_returns_positive_wave_celerity(self, tehri_config):
        result = rapid_estimate(tehri_config, ensemble_size=3)
        assert result["wave_celerity_ms"] > 0

    def test_arrival_times_dict_non_empty(self, tehri_config):
        result = rapid_estimate(tehri_config, ensemble_size=3)
        assert len(result["arrival_times"]) >= 1

    def test_inundation_area_positive(self, tehri_config):
        result = rapid_estimate(tehri_config, ensemble_size=3)
        assert result["inundation_area_km2"] > 0

    def test_affected_population_non_negative(self, tehri_config):
        result = rapid_estimate(tehri_config, ensemble_size=3)
        assert result["affected_population"] >= 0
