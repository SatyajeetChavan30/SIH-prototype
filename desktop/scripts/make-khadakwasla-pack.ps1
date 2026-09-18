<#
.SYNOPSIS
  Build the Khadakwasla data pack for the JalRaksha desktop app.

.DESCRIPTION
  Exports one completed Khadakwasla run, plus the inputs a NEW Khadakwasla run
  needs offline, into dist/packs/JalRaksha-khadakwasla-<sha>.jrpack. Import it
  in the desktop app with File -> Import data pack.

  Contents:
    * the run: by default the flagship e2e09ea3... (khadakwasla_drain_to_green,
      a real solve reaching zero severe cells; CLAUDE.md), else the newest
      completed Khadakwasla run that has a keyframe manifest on disk
    * data/dem/dem_18.44_73.77_clipped.tif - Copernicus DEM GLO-30 (approved)
    * the Pune-basin (EPSG:32643) Earth Engine caches the impact panel reads:
      GHS-POP (area-corrected v2 only - pre-fix rasters carry the 25x undercount
      and are never packed), GHS-BUILT-S and ESA WorldCover cropland, all CC BY 4.0

  Runs from a checkout that has the data; it is not built in CI, because the
  source data is not in git.

.PARAMETER RunId
  Pack this run instead of choosing one.

.PARAMETER Python
  Interpreter with the service's dependencies (default: python).
#>
param(
    [string]$RunId = "",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
$env:PYTHONPATH = "$repo\services\api;$repo"
$env:JALRAKSHA_DATA_DIR = "./data"

if (-not $RunId) {
    $RunId = & $Python (Join-Path $PSScriptRoot "pick_pack_run.py") khadakwasla --prefer e2e09ea3201d4d42b7a7dbcd5fac4b81
    $RunId = "$RunId".Trim()
    if (-not $RunId) { throw "No completed Khadakwasla run with a keyframe manifest was found in data/jalraksha.db" }
}
Write-Host "Packing Khadakwasla run $RunId"

$sha = (git rev-parse --short HEAD).Trim()
$out = Join-Path $repo "dist\packs\JalRaksha-khadakwasla-$sha.jrpack"

$copernicus = "Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus 2014-2018, provided under COPERNICUS by the European Union and ESA"
$ghsPop = "GHS-POP R2023A (JRC/GHSL/P2023A/GHS_POP), European Commission Joint Research Centre, CC BY 4.0"
$ghsBuilt = "GHS-BUILT-S R2023A (JRC/GHSL/P2023A/GHS_BUILT_S), European Commission Joint Research Centre, CC BY 4.0"
$worldCover = "ESA WorldCover 10 m v200 (ESA/WorldCover/v200), (c) ESA WorldCover project, CC BY 4.0"

$args = @("-m", "jalraksha_service.data_packs", "export",
    "--run-id", $RunId, "--out", $out, "--name", "Khadakwasla Dam (Mutha basin, Pune)",
    "--include", "data/dem/dem_18.44_73.77_clipped.tif=$copernicus")

foreach ($file in Get-ChildItem data/gee/ghsl -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -like "epsg32643_*" -and ($_.Name -like "*_areacorrected.tif" -or $_.Name -eq "ghsl_manifest_v2.json") }) {
    $args += @("--include", "$($file.FullName)=$ghsPop")
}
foreach ($dir in Get-ChildItem data/gee/ghs_built -Directory -Filter "epsg32643_*" -ErrorAction SilentlyContinue) {
    $args += @("--include", "$($dir.FullName)=$ghsBuilt")
}
foreach ($dir in Get-ChildItem data/gee/worldcover_grid -Directory -Filter "epsg32643_*" -ErrorAction SilentlyContinue) {
    $args += @("--include", "$($dir.FullName)=$worldCover")
}

& $Python @args
if ($LASTEXITCODE -ne 0) { throw "data pack export failed" }
Write-Host "Pack written: $out"
