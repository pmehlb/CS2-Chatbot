# CS2-Chatbot Build Script (PowerShell)
# Builds a portable executable for Windows

param(
    [switch]$Clean,
    [switch]$Run,
    [switch]$Help
)

if ($Help) {
    Write-Host "CS2-Chatbot Build Script" -ForegroundColor Green
    Write-Host "Usage: .\packaging\build.ps1 [-Clean] [-Run] [-Help]" -ForegroundColor White
    Write-Host "  -Clean  Clean build artifacts before building"
    Write-Host "  -Run    After a successful build, copy .for_personal_use\chatbot_settings.json"
    Write-Host "          into release\ (if it is there) and start the executable"
    Write-Host "  -Help   Show this help message"
    exit 0
}

# This script lives in packaging/; run from the repo root so all relative paths
# (venv, dist, release, spec) resolve regardless of where it was invoked from.
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Building CS2-Chatbot..." -ForegroundColor Green

# Check if virtual environment exists
if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found!" -ForegroundColor Red
    exit 1
}

# Clean if requested
if ($Clean) {
    Write-Host "Cleaning build artifacts..." -ForegroundColor Yellow
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
    if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
    if (Test-Path "release") { Remove-Item "release" -Recurse -Force }
}

# Remove old executable to ensure fresh build
if (Test-Path ".\release\CS2-Chatbot.exe") {
    Remove-Item ".\release\CS2-Chatbot.exe" -Force
}

Write-Host "Starting build..." -ForegroundColor Cyan

# Build directly with PyInstaller using our spec file
& ".\venv\Scripts\pyinstaller" "--clean" "--noconfirm" "packaging\CS2-Chatbot.spec"
$exitCode = $LASTEXITCODE

# Create release folder and copy files
if ($exitCode -eq 0 -and (Test-Path ".\dist\CS2-Chatbot.exe")) {
    # Create release folder
    if (-not (Test-Path "release")) { New-Item -ItemType Directory -Path "release" -Force | Out-Null }
    
    # Copy executable and documentation
    Copy-Item ".\dist\CS2-Chatbot.exe" ".\release\CS2-Chatbot.exe" -Force
    if (Test-Path "README.md") { Copy-Item "README.md" ".\release\" -Force }

    $fileInfo = Get-Item ".\release\CS2-Chatbot.exe"
    $sizeInMB = [math]::Round($fileInfo.Length / 1MB, 1)
    
    Write-Host ""
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "Executable: .\release\CS2-Chatbot.exe ($sizeInMB MB)" -ForegroundColor Cyan
    Write-Host "Ready for distribution!" -ForegroundColor Green

    if ($Run) {
        # The app reads chatbot_settings.json from the folder the .exe sits in,
        # so a personal copy dropped into release\ gives the fresh build the
        # real API keys and rules. Every step here is optional: a missing file
        # or a locked file only costs the settings, and the app writes its own
        # defaults on first launch.
        $personalSettings = ".\.for_personal_use\chatbot_settings.json"
        if (Test-Path $personalSettings) {
            try {
                Copy-Item $personalSettings ".\release\chatbot_settings.json" -Force -ErrorAction Stop
                Write-Host ""
                Write-Host "Copied personal settings into .\release\" -ForegroundColor Cyan
            } catch {
                Write-Host ""
                Write-Host "Could not copy personal settings: $($_.Exception.Message)" -ForegroundColor Yellow
                Write-Host "Starting anyway - the app uses whatever settings are in release\." -ForegroundColor Yellow
            }
        } else {
            Write-Host ""
            Write-Host "No $personalSettings - starting with the settings already in release\." -ForegroundColor Yellow
        }

        Write-Host "Starting CS2-Chatbot..." -ForegroundColor Green
        try {
            $releaseDir = (Resolve-Path ".\release").Path
            Start-Process -FilePath (Join-Path $releaseDir "CS2-Chatbot.exe") `
                          -WorkingDirectory $releaseDir -ErrorAction Stop
        } catch {
            Write-Host "Could not start the executable: $($_.Exception.Message)" -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host ""
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
