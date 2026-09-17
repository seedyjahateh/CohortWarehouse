# DESTRUCTIVE local helper: recreate the warehouse container volume, bootstrap, and load the fictional
# test vocabulary. Intended for development and the disposable-database integration tests only.
param([switch]$Yes)
$ErrorActionPreference = "Stop"
if (-not $Yes) { throw "This deletes the local warehouse volume. Re-run with -Yes to confirm." }
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
docker compose down -v
docker compose up -d --wait warehouse
& $python -m cohortwarehouse bootstrap
& $python -m cohortwarehouse load-vocabulary tests/fixtures/vocabulary --license-note "Fictional test-only vocabulary (scripts/build_fixture.py)"
