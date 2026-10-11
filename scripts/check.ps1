$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath (Join-Path $taskRepoRoot 'backend')
try {
    & uv run --locked ruff check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv run --locked ruff format --check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv run --locked pytest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv run --locked alembic check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
Push-Location -LiteralPath (Join-Path $taskRepoRoot 'frontend')
try {
    & pnpm.cmd build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
