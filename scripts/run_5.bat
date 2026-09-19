@echo off
cd /d "D:\pd\chosen one\SIH prototype"
C:\Python314\python.exe -u scripts\run_khadakwasla_drainage_check.py --margins 80,420,200,200 --resolution 500 --duration-h 96 --members 40 --solver sph --backend cuda --sph-window-km 1.5 --sph-particles 150000 --dem data/dem_wide/dem/dem_18.44_73.77_clipped.tif --label "Khadakwasla GPU - 500x400 km, 500 m, 96 h, 40 members" > data\runs\khadakwasla_gpu_500x400_500m_96h_40m.log 2>&1
