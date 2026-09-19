import os
import subprocess
import sys
from pathlib import Path

repo_root = Path(r"D:\pd\chosen one\SIH prototype")
log_path = repo_root / "data" / "runs" / "khadakwasla_gpu_500x400_500m_96h_40m.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
log_file = open(log_path, "w", encoding="utf-8")

cmd = [
    sys.executable,
    "-u",
    str(repo_root / "scripts" / "run_khadakwasla_drainage_check.py"),
    "--margins", "80,420,200,200",
    "--resolution", "500",
    "--duration-h", "96",
    "--members", "40",
    "--solver", "sph",
    "--backend", "cuda",
    "--sph-window-km", "1.5",
    "--sph-particles", "150000",
    "--dem", str(repo_root / "data" / "dem_wide" / "dem" / "dem_18.44_73.77_clipped.tif"),
    "--label", "Khadakwasla GPU - 500x400 km, 500 m, 96 h, 40 members",
]

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
env["JALRAKSHA_DATA_DIR"] = "./data"
env["JALRAKSHA_GEE_PROJECT"] = "sih-prototype-506812"

flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | 0x01000000

proc = subprocess.Popen(
    cmd,
    cwd=str(repo_root),
    env=env,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    creationflags=flags,
)

print(f"LAUNCHED_PID={proc.pid}")
log_file.close()
