<#
    Render the architecture deck to per-slide PNGs for visual QA.

        powershell -ExecutionPolicy Bypass -File tools\render_architecture_deck.ps1

    There is no LibreOffice on this machine, so the export is driven through
    PowerPoint's COM automation interface. PowerPoint must not already have the
    deck open under a lock.
#>

param(
    [string]$Deck = "JalRaksha_Architecture_Deck.pptx",
    [int]$Width = 2000
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$deckPath = Join-Path $root $Deck
if (-not (Test-Path $deckPath)) { throw "no such deck: $deckPath" }

$pngDir = Join-Path $PSScriptRoot "render-architecture"
if (Test-Path $pngDir) { Remove-Item $pngDir -Recurse -Force }
New-Item -ItemType Directory -Path $pngDir | Out-Null

$ppt = New-Object -ComObject PowerPoint.Application
try {
    # msoTrue = -1. Opened read-only, untitled:no, withwindow:no.
    $pres = $ppt.Presentations.Open($deckPath, -1, 0, 0)
    try {
        $height = [int][math]::Round($Width * 7.5 / 13.333)
        for ($i = 1; $i -le $pres.Slides.Count; $i++) {
            $out = Join-Path $pngDir ("slide{0:d2}.png" -f $i)
            $pres.Slides.Item($i).Export($out, "PNG", $Width, $height)
            Write-Output "rendered $out"
        }
    }
    finally {
        $pres.Close()
    }
}
finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
