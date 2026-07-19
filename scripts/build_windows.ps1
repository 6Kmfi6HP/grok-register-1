# Build a one-dir Windows x64 package with PyInstaller.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 [-Version v1.0.0]
param(
    [string]$Version = $env:GROK_REGISTER_VERSION
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($Version)) { $Version = "dev" }
$Version = $Version.TrimStart("v")
$Platform = "windows"
$Arch = "x64"
Write-Host "[build] version=$Version platform=$Platform arch=$Arch"

$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py -3" }

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python -m pip install "pyinstaller>=6.0,<7"

$env:GROK_REGISTER_VERSION = "v$Version"
# Stamp version into app_paths.py (restore after freeze so the working tree stays clean).
$appPaths = Join-Path $Root "app_paths.py"
$appPathsBackup = $null
if (Test-Path $appPaths) {
    $appPathsBackup = Join-Path $env:TEMP ("app_paths_backup_{0}.py" -f [guid]::NewGuid().ToString("N"))
    Copy-Item -Force $appPaths $appPathsBackup
    $text = Get-Content -Raw -Path $appPaths
    $old = '__version__ = "0.0.0+dev"'
    $new = "__version__ = `"v$Version`""
    if ($text.Contains($old)) {
        # Preserve final newline style
        Set-Content -Path $appPaths -Value ($text.Replace($old, $new)) -NoNewline
        Write-Host "[build] stamped version v$Version"
    }
}

function Restore-AppPaths {
    if ($script:appPathsBackup -and (Test-Path $script:appPathsBackup)) {
        Copy-Item -Force $script:appPathsBackup $appPaths
        Remove-Item -Force $script:appPathsBackup
        Write-Host "[build] restored app_paths.py"
        $script:appPathsBackup = $null
    }
}

try {
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

    & $Python -m PyInstaller --noconfirm --clean grok-register.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}
finally {
    Restore-AppPaths
}

$AppDir = Join-Path $Root "dist\grok-register"
if (-not (Test-Path $AppDir)) {
    throw "Expected one-dir output at $AppDir"
}

$Exe = Join-Path $AppDir "grok-register.exe"
if (-not (Test-Path $Exe)) {
    throw "Missing executable: $Exe"
}

# Clean config template next to exe
$Example = Join-Path $Root "config.example.json"
if (Test-Path $Example) {
    Copy-Item -Force $Example (Join-Path $AppDir "config.example.json")
}

# Start helpers
@"
@echo off
cd /d "%~dp0"
start "" "grok-register.exe" %*
"@ | Set-Content -Encoding ASCII (Join-Path $AppDir "start-gui.bat")

@"
@echo off
cd /d "%~dp0"
"grok-register.exe" cli %*
"@ | Set-Content -Encoding ASCII (Join-Path $AppDir "start-cli.bat")

@"
@echo off
cd /d "%~dp0"
"grok-register.exe" %*
"@ | Set-Content -Encoding ASCII (Join-Path $AppDir "grok-register-cli.bat")

# Secret guard
if (Test-Path (Join-Path $AppDir "config.json")) {
    throw "secret config.json must not be bundled"
}
if (Get-ChildItem -Path $AppDir -Filter "accounts_*.txt" -ErrorAction SilentlyContinue) {
    throw "accounts_*.txt must not be bundled"
}
$cpa = Join-Path $AppDir "cpa_auths"
if ((Test-Path $cpa) -and (Get-ChildItem -Path $cpa -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
    throw "non-empty cpa_auths must not be bundled"
}

$ArchiveName = "grok-register-v$Version-$Platform-$Arch.zip"
$OutZip = Join-Path $Root "dist\$ArchiveName"
if (Test-Path $OutZip) { Remove-Item -Force $OutZip }

Compress-Archive -Path $AppDir -DestinationPath $OutZip -Force
if (-not (Test-Path $OutZip)) { throw "Archive missing: $OutZip" }

$size = (Get-Item $OutZip).Length
if ($size -lt 1000000) { throw "Archive suspiciously small ($size bytes): $OutZip" }

Write-Host "[build] OK: $OutZip ($size bytes)"

# Smoke: --help / --version (windowed binary may not attach console; use Start-Process)
Write-Host "[build] smoke: launching --version (best-effort)"
try {
    $p = Start-Process -FilePath $Exe -ArgumentList "--version" -Wait -PassThru -NoNewWindow
    Write-Host "[build] --version exit=$($p.ExitCode)"
} catch {
    Write-Host "[build] --version smoke skipped: $_"
}

Write-Host "[build] done"
