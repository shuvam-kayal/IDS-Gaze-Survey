$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $Root
$DevDatabaseUrl = "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop is required." }
if (-not (Test-Path $VenvPython)) { throw "Missing .venv. Run .\scripts\setup.ps1 first." }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running or is not accessible." }

& docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL Compose service failed to start." }
$env:DATABASE_URL = $DevDatabaseUrl
& $VenvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Development database migration failed." }
& docker compose up --build
