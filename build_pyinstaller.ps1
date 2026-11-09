param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    $requiredPaths = @(
        "TTSMobileHelper.spec",
        "socket.io.js",
        "mobile_ui.html",
        "localization"
    )

    foreach ($relativePath in $requiredPaths) {
        $fullPath = Join-Path $scriptDir $relativePath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            throw "Build-Datei fehlt: $fullPath"
        }
    }

    & $Python -m PyInstaller --noconfirm --clean TTSMobileHelper.spec
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $exePath = Join-Path $scriptDir "dist\TTSMobileHelper\TTSMobileHelper.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Build wurde beendet, aber die Exe wurde nicht gefunden: $exePath"
    }

    Write-Host ""
    Write-Host "Build fertig: $exePath"
}
finally {
    $buildPath = Join-Path $scriptDir "build"
    $resolvedScriptDir = [System.IO.Path]::GetFullPath($scriptDir)
    $resolvedBuildPath = [System.IO.Path]::GetFullPath($buildPath)

    if (
        (Test-Path -LiteralPath $resolvedBuildPath) -and
        ($resolvedBuildPath -eq (Join-Path $resolvedScriptDir "build"))
    ) {
        Remove-Item -LiteralPath $resolvedBuildPath -Recurse -Force
        Write-Host "Temporaerer Build-Ordner geloescht: $resolvedBuildPath"
    }

    Pop-Location
}
