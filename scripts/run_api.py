"""
Start the JalRaksha API for local/demo use.

This wrapper exists because the launch configuration format has no field for
environment variables, and the API needs two of them set before any module is
imported:

  CELERY_EAGER=1        run Celery tasks synchronously in-process, so POST /runs
                        works without a Redis broker and a separate worker
                        (services/api/jalraksha_service/worker.py, ~line 27).
  JALRAKSHA_DATA_DIR    where the pre-baked DEMs, keyframes, exports and the
                        SQLite database live (config.py, ~line 17).

It also pins the working directory to the repo root. That is not cosmetic: the
export paths recorded in data/jalraksha.db are RELATIVE, and main.py resolves
them against the process CWD, so starting the API from anywhere else silently
breaks every /files/... URL the frontend requests.

Usage:
    python scripts/run_api.py            # port 8000
    python scripts/run_api.py --port 8001
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true",
                        help="Reload on source changes (development only).")
    parser.add_argument("--broker", action="store_true",
                        help="Use a real Celery broker/worker instead of running "
                             "tasks eagerly in-process. Requires Redis.")
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    os.environ.setdefault("JALRAKSHA_DATA_DIR", "./data")
    # Earth Engine. `earthengine authenticate` writes credentials to
    # ~/.config/earthengine, but EE also needs a Cloud project with the EE API
    # enabled, and that is what this variable names. Without it gee_status()
    # reports "not set" and BOTH the Sentinel-1 overlay and the GHSL
    # population-at-risk panel go dark, even though the credentials are valid.
    # setdefault, so a real environment variable still wins.
    os.environ.setdefault("JALRAKSHA_GEE_PROJECT", "sih-prototype-506812")
    if not args.broker:
        os.environ["CELERY_EAGER"] = "1"

    api_dir = REPO_ROOT / "services" / "api"
    if not (api_dir / "jalraksha_service" / "main.py").exists():
        raise SystemExit(f"API package not found under {api_dir}")
    sys.path.insert(0, str(api_dir))

    import uvicorn

    print(f"[run_api] repo root      : {REPO_ROOT}")
    print(f"[run_api] data dir       : {os.environ['JALRAKSHA_DATA_DIR']}")
    print(f"[run_api] eager tasks    : {os.environ.get('CELERY_EAGER') == '1'}")
    print(f"[run_api] gee project    : {os.environ.get('JALRAKSHA_GEE_PROJECT') or '<unset>'}")
    print(f"[run_api] listening on   : http://{args.host}:{args.port}")
    uvicorn.run("jalraksha_service.main:app", host=args.host, port=args.port,
                reload=args.reload, app_dir=str(api_dir))


if __name__ == "__main__":
    main()
