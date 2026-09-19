import os
import sys
from pathlib import Path

repo_root = Path(r"D:\pd\chosen one\SIH prototype")
os.chdir(repo_root)

log_path = repo_root / "data" / "runs" / "khadakwasla_gpu_500x400_500m_96h_40m.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

log_file = open(log_path, "w", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["JALRAKSHA_DATA_DIR"] = "./data"
os.environ["JALRAKSHA_GEE_PROJECT"] = "sih-prototype-506812"

sys.argv = [
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

import runpy
runpy.run_path(str(repo_root / "scripts" / "run_khadakwasla_drainage_check.py"), run_name="__main__")
