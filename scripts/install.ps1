<#
.SYNOPSIS
Forge one-command bootstrap installer (Windows PowerShell).
#>

param(
    [string]$Version = $env:FORGE_VERSION
)

$ErrorActionPreference = "Stop"

$ReleaseBase = if ($env:FORGE_RELEASE_BASE) { $env:FORGE_RELEASE_BASE } else { "https://github.com/anomalyco/forge/releases/download" }
$Target = "windows-x64"

if (-not $Version) {
    $Version = if ($env:FORGE_ALPHA_VERSION) { $env:FORGE_ALPHA_VERSION } else { "latest" }
}

Write-Host "Forge installer - $Version ($Target)"

if ($Version -eq "latest") {
    Write-Host "Resolving latest version..."
    try {
        $Version = (Invoke-WebRequest -Uri "$ReleaseBase/latest.txt" -UseBasicParsing).Content.Trim()
    } catch {
        Write-Error "unable to resolve latest version"
        exit 1
    }
}

$ArchiveName = "forge-${Version}-${Target}.tar.gz"
$ChecksumName = "forge-${Version}-${Target}.sha256"

$TmpDir = Join-Path $env:TEMP "forge-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null
Push-Location $TmpDir
try {
    Write-Host "Downloading $ReleaseBase/$Version/$ArchiveName..."
    Invoke-WebRequest -Uri "$ReleaseBase/$Version/$ArchiveName" -OutFile $ArchiveName -UseBasicParsing

    Write-Host "Downloading checksum..."
    Invoke-WebRequest -Uri "$ReleaseBase/$Version/$ChecksumName" -OutFile $ChecksumName -UseBasicParsing

    Write-Host "Verifying checksum..."
    $Expected = (Get-Content $ChecksumName).Split(' ')[0].Trim()
    $Actual = (Get-FileHash -Algorithm SHA256 $ArchiveName).Hash.ToLower()
    if ($Expected -ne $Actual) {
        Write-Error "checksum mismatch: expected $Expected, got $Actual"
        exit 1
    }
    Write-Host "Checksum verified."

    Write-Host "Extracting..."
    tar xzf $ArchiveName

    $Extracted = Get-ChildItem -Directory | Where-Object { $_.Name -like "forge-*" } | Select-Object -First 1
    if (-not $Extracted) {
        Write-Error "extraction did not produce expected directory"
        exit 1
    }

    $Exe = Join-Path $Extracted.FullName "bin" "forge.exe"
    if (-not (Test-Path $Exe)) {
        Write-Error "executable not found: $Exe"
        exit 1
    }

    Write-Host "Running installer..."
    & $Exe install --version $Version --release-base "$ReleaseBase/$Version"

} finally {
    Pop-Location
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}

Write-Host "Forge $Version installation complete."
