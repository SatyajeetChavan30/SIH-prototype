<#
    Export the SIH idea deck to PDF (the only format the portal accepts) and to
    per-slide PNGs for visual QA.

        powershell -ExecutionPolicy Bypass -File tools\sih-presentation\export_pdf.ps1

    There is no LibreOffice on this machine, but PowerPoint is installed, so the
    export is driven through its COM automation interface. PowerPoint must not
    already have the deck open under a lock.
#>

param(
    [string]$Deck = "JalRaksha_SIH2026_Idea.pptx"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$deckPath = Join-Path $root $Deck
if (-not (Test-Path $deckPath)) { throw "no such deck: $deckPath" }

$pdfPath = [System.IO.Path]::ChangeExtension($deckPath, ".pdf")
$pngDir = Join-Path $PSScriptRoot "render"
if (Test-Path $pngDir) { Remove-Item $pngDir -Recurse -Force }
New-Item -ItemType Directory -Path $pngDir | Out-Null

$ppt = New-Object -ComObject PowerPoint.Application
try {
    # msoTrue = -1. Opened read-only, untitled:no, withwindow:no.
    $pres = $ppt.Presentations.Open($deckPath, -1, 0, 0)
    try {
        # ppSaveAsPDF = 32
        $pres.SaveAs($pdfPath, 32)
        Write-Output "PDF  -> $pdfPath"

        # 1600 px wide keeps the text legible when read back for QA.
        $pres.Export($pngDir, "PNG", 1600, 900)
        $n = (Get-ChildItem $pngDir -Filter *.PNG).Count
        Write-Output "PNGs -> $pngDir ($n slides)"
    }
    finally {
        $pres.Close()
    }
}
finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
