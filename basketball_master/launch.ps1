# Keep path handling here so UTF-8 configuration and Unicode folders work in BAT.
param([switch]$CheckPython)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

function Get-UsablePython([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return }
    $Candidate = $Candidate.Trim().Trim('"')
    # Skip per-user execution aliases, not real Store-installed package binaries.
    if ($Candidate -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/][^\\/]+$') { return }
    try {
        if ((Split-Path -Leaf $Candidate) -ieq 'pythonw.exe') {
            $Candidate = Join-Path (Split-Path -Parent $Candidate) 'python.exe'
        }
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return }
        $Candidate = (Get-Item -LiteralPath $Candidate).FullName
        & $Candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' *> $null
        if ($LASTEXITCODE -eq 0) { return $Candidate }
    } catch {
        # Stale configuration or a broken executable must allow the next candidate.
    }
}

$python = $null
$settings = Join-Path $PSScriptRoot 'python-path.txt'
if (Test-Path -LiteralPath $settings -PathType Leaf) {
    $python = Get-UsablePython (Get-Content -LiteralPath $settings -Raw -Encoding UTF8)
}

foreach ($relative in @('.venv\Scripts\python.exe', 'venv\Scripts\python.exe')) {
    if ($python) { break }
    $python = Get-UsablePython (Join-Path $root $relative)
}

if (-not $python) {
    foreach ($launcher in @(Get-Command py.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if ($launcher.Source -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/][^\\/]+$') { continue }
        try {
            $resolved = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $python = Get-UsablePython ($resolved | Select-Object -Last 1) }
        } catch {}
        if ($python) { break }
    }
}

if (-not $python) {
    foreach ($command in @(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        $python = Get-UsablePython $command.Source
        if ($python) { break }
    }
}

# Explorer may have an older PATH than a newly opened Anaconda terminal.
foreach ($base in @($env:ProgramData, $env:USERPROFILE, $env:LOCALAPPDATA)) {
    if ($python) { break }
    if ([string]::IsNullOrWhiteSpace($base)) { continue }
    foreach ($name in @('anaconda3', 'miniconda3')) {
        $python = Get-UsablePython (Join-Path $base "$name\python.exe")
        if ($python) { break }
    }
}

if (-not $python -and $env:LOCALAPPDATA) {
    $programs = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $programs -PathType Container) {
        foreach ($folder in @(Get-ChildItem -LiteralPath $programs -Directory -Filter 'Python*' | Sort-Object Name -Descending)) {
            $python = Get-UsablePython (Join-Path $folder.FullName 'python.exe')
            if ($python) { break }
        }
    }
}

if (-not $python) {
    Write-Host 'No usable Python 3.10+ installation was found (Store aliases were skipped).'
    Write-Host 'Install Python or Anaconda, then run setup.bat from its terminal.'
    Write-Host 'Or put the full python.exe path in basketball_master\python-path.txt.'
    exit 2
}

if ($CheckPython) {
    Write-Output $python
    exit 0
}

Write-Host "Starting Basketball Clip Master with: $python"
& $python -m basketball_master @args
exit $LASTEXITCODE
