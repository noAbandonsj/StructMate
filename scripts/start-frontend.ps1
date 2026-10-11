$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command pnpm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Please install pnpm 10 and run pnpm.cmd install --frozen-lockfile in frontend first.'
}
Push-Location -LiteralPath (Join-Path $taskRepoRoot 'frontend')
try {
    & pnpm.cmd dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
