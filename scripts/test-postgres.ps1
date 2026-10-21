param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PytestArgs)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $Root
$Config = Join-Path $Root ".env.test"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Config)) { throw "Missing .env.test. Run .\scripts\setup.ps1 first." }
if (-not (Test-Path $Python)) { throw "Missing .venv. Run .\scripts\setup.ps1 first." }

foreach ($line in Get-Content $Config) {
    if ($line -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}
if (-not $env:TEST_DATABASE_URL) { throw ".env.test does not define TEST_DATABASE_URL." }
& $Python -m pytest -q tests/test_geometry_persistence.py tests/test_authorized_gaze.py tests/test_control_plane.py tests/test_participant_session_state.py tests/test_telemetry_persistence.py @PytestArgs
exit $LASTEXITCODE
