"""
Phase 14: REST API Layer for JalRaksha.

Provides a lightweight HTTP REST API (using Python stdlib http.server) so the
The web dashboard or external tools can trigger simulations and retrieve
results programmatically.

Endpoints:
  GET  /health          — Liveness check
  GET  /api/v1/dams     — List supported demo dams
  POST /api/v1/simulate — Run breach ensemble (JSON body: DamSimRequest)
  GET  /api/v1/gauges   — List downstream gauges for a given lat/lon

Note: This is a minimal synchronous API suitable for local/demo use.
For production, replace with FastAPI + async workers.
"""

from __future__ import annotations

import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs
import threading


# ── Pre-defined demo dams ─────────────────────────────────────────────────────

DEMO_DAMS = [
    {
        "id": "tehri",
        "name": "Tehri Dam",
        "lat": 30.3789,
        "lon": 78.4789,
        "height_m": 260.0,
        "storage_mm3": 3540.0,
        "dam_type": "embankment",
        "river": "Bhagirathi",
        "state": "Uttarakhand",
        "note": "Primary demo scenario for JalRaksha SIH 2026.",
    },
    {
        "id": "bhakra",
        "name": "Bhakra Dam",
        "lat": 31.4167,
        "lon": 76.4333,
        "height_m": 226.0,
        "storage_mm3": 9340.0,
        "dam_type": "gravity",
        "river": "Sutlej",
        "state": "Himachal Pradesh",
        "note": "Second largest dam in India — for sensitivity comparison.",
    },
]


# ── Downstream gauge definitions ──────────────────────────────────────────────

def get_downstream_gauges(lat: float, lon: float, dam_id: Optional[str] = None) -> List[Dict]:
    """
    Return downstream gauge definitions for a given dam location.

    Currently hard-coded for the Tehri corridor (Koteshwar → Haridwar).
    For custom dams, returns generic distance-based placeholders.

    Args:
        lat: Dam latitude (degrees).
        lon: Dam longitude (degrees).
        dam_id: Optional dam ID for lookup.

    Returns:
        List of gauge dicts with: name, distance_km, lat, lon, river.
    """
    if dam_id == "tehri" or (29.0 <= lat <= 31.5 and 77.0 <= lon <= 80.0):
        return [
            {"name": "Koteshwar",  "distance_km": 13.0,  "lat": 30.3167, "lon": 78.4833, "river": "Bhagirathi"},
            {"name": "Devprayag",  "distance_km": 28.0,  "lat": 30.15, "lon": 78.60, "river": "Ganga"},
            {"name": "Rishikesh",  "distance_km": 34.8,  "lat": 30.0869, "lon": 78.2676, "river": "Ganga"},
            {"name": "Haridwar",   "distance_km": 58.4,  "lat": 29.9457, "lon": 78.1642, "river": "Ganga"},
        ]
    else:
        # Generic placeholders at 10, 25, 50, 100 km downstream
        return [
            {"name": "Gauge_10km",  "distance_km": 10.0,  "lat": lat - 0.09, "lon": lon},
            {"name": "Gauge_25km",  "distance_km": 25.0,  "lat": lat - 0.22, "lon": lon},
            {"name": "Gauge_50km",  "distance_km": 50.0,  "lat": lat - 0.45, "lon": lon},
            {"name": "Gauge_100km", "distance_km": 100.0, "lat": lat - 0.90, "lon": lon},
        ]


# ── Analytic rapid estimate (no solver required) ──────────────────────────────

def rapid_estimate(dam_config: Dict, ensemble_size: int = 10) -> Dict:
    """
    Generate a rapid analytic estimate of flood parameters without running
    the full 2D SWE solver.

    Uses shallow-water wave-celerity approximation and Xu-Zhang peak outflow
    regression. Suitable for API demo responses; not for production use.

    Args:
        dam_config: Dam parameter dict (name, lat, lon, height_m, storage_mm3).
        ensemble_size: Number of synthetic ensemble members.

    Returns:
        Dict with: q_peak, c_wave, arrival_times, inundation_km2, affected_pop.
    """
    from jalraksha.terrain.breach import synthesize_breach_ensemble, ensemble_statistics

    try:
        hydrographs = synthesize_breach_ensemble(dam_config, num_samples=ensemble_size)
        stats = ensemble_statistics(hydrographs)
        q_peak = stats["q_peak_median"]
    except Exception:
        # Fallback: Froehlich (1995) simplified
        height = dam_config.get("height_m", 100.0)
        storage = dam_config.get("storage_mm3", 1000.0)
        q_peak = 0.607 * (storage * 1e6) ** 0.295 * height ** 0.838  # m³/s

    height = dam_config.get("height_m", 100.0)
    c_wave = 0.5 * math.sqrt(9.81 * height)  # Shallow-water celerity (m/s)

    # Arrival times at standard distances
    distances_km = [13.0, 28.0, 34.8, 58.4]
    gauge_names = ["Koteshwar", "Devprayag", "Rishikesh", "Haridwar"]
    arrival_times = {}
    for name, dist_km in zip(gauge_names, distances_km):
        t_s = (dist_km * 1000.0) / c_wave
        spread = 0.2 * t_s
        arrival_times[name] = {
            "median_s": round(t_s, 0),
            "median_min": round(t_s / 60.0, 1),
            "p05_min": round((t_s - spread) / 60.0, 1),
            "p95_min": round((t_s + spread) / 60.0, 1),
            "distance_km": dist_km,
        }

    inundation_km2 = round(0.0012 * q_peak, 2)
    affected_pop = int(inundation_km2 * 850)

    return {
        "dam_name": dam_config.get("name", "Unknown"),
        "q_peak_median_m3s": round(q_peak, 0),
        "wave_celerity_ms": round(c_wave, 2),
        "arrival_times": arrival_times,
        "inundation_area_km2": inundation_km2,
        "affected_population": affected_pop,
        "economic_loss_crore_inr": round(inundation_km2 * 12.5, 1),
        "method": "rapid_analytic",
        "note": "Rapid analytic estimate. Run full SWE solver for authoritative results.",
    }


# ── HTTP Request Handler ──────────────────────────────────────────────────────

class JalRakshaAPIHandler(BaseHTTPRequestHandler):
    """
    Minimal HTTP request handler for the JalRaksha REST API.

    Routes:
      GET  /health
      GET  /api/v1/dams
      GET  /api/v1/gauges?lat=&lon=&dam_id=
      POST /api/v1/simulate
    """

    def log_message(self, format_str, *args):
        """Suppress default server log; use print for important messages."""
        pass

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Optional[Dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "JalRaksha API v1"})

        elif path == "/api/v1/dams":
            self._send_json(200, {"dams": DEMO_DAMS})

        elif path == "/api/v1/gauges":
            try:
                lat = float(params.get("lat", [30.3789])[0])
                lon = float(params.get("lon", [78.4789])[0])
                dam_id = params.get("dam_id", [None])[0]
            except (ValueError, IndexError):
                self._send_json(400, {"error": "Invalid lat/lon parameters."})
                return
            gauges = get_downstream_gauges(lat, lon, dam_id)
            self._send_json(200, {"gauges": gauges})

        else:
            self._send_json(404, {"error": f"Unknown endpoint: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/v1/simulate":
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"error": "Request body must be JSON."})
                return

            # Validate required fields
            required = ["name", "lat", "lon", "height_m", "storage_mm3"]
            missing = [k for k in required if k not in body]
            if missing:
                self._send_json(400, {"error": f"Missing fields: {missing}"})
                return

            try:
                from jalraksha.hardening import validate_dam_config, HardeningError
                validate_dam_config(body)
            except Exception as exc:
                self._send_json(422, {"error": str(exc)})
                return

            try:
                ensemble_size = int(body.get("ensemble_size", 10))
                result = rapid_estimate(body, ensemble_size=ensemble_size)
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"error": f"Simulation error: {exc}"})

        else:
            self._send_json(404, {"error": f"Unknown POST endpoint: {path}"})


# ── Server lifecycle ──────────────────────────────────────────────────────────

def start_api_server(host: str = "127.0.0.1", port: int = 8502) -> HTTPServer:
    """
    Start the JalRaksha API server in a background thread.

    Args:
        host: Bind address (default: localhost only).
        port: TCP port (default: 8502 — distinct from the FastAPI service on 8000).

    Returns:
        HTTPServer instance (call .shutdown() to stop).
    """
    server = HTTPServer((host, port), JalRakshaAPIHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[JalRaksha API] Listening on http://{host}:{port}")
    return server


def stop_api_server(server: HTTPServer) -> None:
    """Stop the API server gracefully."""
    server.shutdown()
