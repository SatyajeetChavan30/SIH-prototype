"""
Upload the conditioned DEM to Cesium ion as a terrain asset (integration brief §5.5.1).

STATUS: best-effort, UNVERIFIED. Written without a Cesium ion account or network
access to test against, in an environment with no `cesium-terrain-builder` (ctb)
binary either. Read Cesium's current ion REST API docs and confirm the request
shapes below before relying on this — the ion API has changed over time.

Why this exists: the brief's whole point about 3D terrain (§5.5.1) is that it must
be built from the SAME DEM the solver ran on, or the flood overlay visibly floats
through hills / clips underground at the seams — the most common failure mode in
dam-break 3D demos. Self-hosting via `cesium-terrain-builder` needs a binary that
isn't installed anywhere in this environment; uploading to Cesium ion (free tier
covers one small catchment) is the lower-setup-risk alternative the user chose.

Usage (once you have an ion token — https://ion.cesium.com/tokens):
    CESIUM_ION_TOKEN=... python tools/cesium/upload_terrain_to_ion.py \\
        --dem data/dem/mosaic_30.38_78.48.tif --name "Tehri catchment terrain"

On success, prints the ion asset ID — set it as VITE_CESIUM_ION_ASSET_ID (and the
token as VITE_CESIUM_ION_TOKEN) for the frontend build; see
frontend/src/panels/Scene3D.jsx's useTerrainProvider().
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ION_API_BASE = "https://api.cesium.com/v1"


def upload_terrain_asset(dem_path: Path, name: str, token: str, description: str = "") -> int:
    """
    Upload a GeoTIFF DEM to Cesium ion as a TERRAIN asset.

    Cesium ion's asset-upload flow (as of the 2024-era REST API):
      1. POST /v1/assets to register the asset and get an S3 upload location.
      2. Upload the file to the returned S3 location.
      3. POST the returned completion callback to trigger ion's tiling job.
      4. Poll GET /v1/assets/{id} until status == "COMPLETE".

    This has NOT been run against the real API in this environment. Treat the
    exact field names below as a starting point to verify against Cesium's
    current docs (https://cesium.com/learn/ion/rest-api/), not a guarantee.

    Returns:
        The ion asset ID (int) to use as VITE_CESIUM_ION_ASSET_ID.
    """
    import requests

    headers = {"Authorization": f"Bearer {token}"}

    create_resp = requests.post(
        f"{ION_API_BASE}/assets",
        headers=headers,
        json={
            "name": name,
            "description": description or f"JalRaksha conditioned DEM: {dem_path.name}",
            "type": "TERRAIN",
            "options": {"sourceType": "RASTER_TERRAIN"},
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    payload = create_resp.json()
    asset_id = payload["assetMetadata"]["id"]
    upload_location = payload["uploadLocation"]
    on_complete = payload["onComplete"]

    # Upload the GeoTIFF to the pre-signed location ion gave us.
    import boto3  # optional dep; only needed for this script

    session = boto3.Session(
        aws_access_key_id=upload_location["accessKey"],
        aws_secret_access_key=upload_location["secretAccessKey"],
        aws_session_token=upload_location["sessionToken"],
    )
    s3 = session.client("s3", endpoint_url=upload_location.get("endpoint"))
    key = upload_location["prefix"] + dem_path.name
    s3.upload_file(str(dem_path), upload_location["bucket"], key)

    requests.post(
        f"{ION_API_BASE}{on_complete['url']}",
        headers=headers,
        json=on_complete.get("fields", {}),
        timeout=30,
    ).raise_for_status()

    # Poll for the tiling job to finish.
    print(f"Uploaded; ion asset {asset_id} is tiling...")
    for _ in range(120):
        status_resp = requests.get(f"{ION_API_BASE}/assets/{asset_id}", headers=headers, timeout=30)
        status_resp.raise_for_status()
        status = status_resp.json().get("status")
        print(f"  status={status}")
        if status == "COMPLETE":
            return asset_id
        if status == "ERROR":
            raise RuntimeError(f"ion tiling failed for asset {asset_id}")
        time.sleep(5)
    raise TimeoutError(f"ion asset {asset_id} did not finish tiling in time")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", type=Path, default=Path("data/dem/mosaic_30.38_78.48.tif"),
                         help="Conditioned/raw DEM GeoTIFF to upload (default: pre-staged Tehri mosaic)")
    parser.add_argument("--name", default="JalRaksha terrain")
    args = parser.parse_args()

    token = os.environ.get("CESIUM_ION_TOKEN")
    if not token:
        print("ERROR: set CESIUM_ION_TOKEN (get one at https://ion.cesium.com/tokens)", file=sys.stderr)
        sys.exit(1)
    if not args.dem.exists():
        print(f"ERROR: DEM not found: {args.dem}", file=sys.stderr)
        sys.exit(1)

    asset_id = upload_terrain_asset(args.dem, args.name, token)
    print(f"\nDone. Set:\n  VITE_CESIUM_ION_TOKEN={token}\n  VITE_CESIUM_ION_ASSET_ID={asset_id}")


if __name__ == "__main__":
    main()
