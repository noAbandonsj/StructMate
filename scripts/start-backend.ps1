param([switch]$Reload)

$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Please install uv and run uv sync --locked in backend first.'
}
Push-Location -LiteralPath (Join-Path $taskRepoRoot 'backend')
try {
    $taskServerArgs = @(
        'run', '--locked', 'uvicorn', 'capstone.main:create_app',
        '--factory', '--host', '127.0.0.1', '--port', '8000'
    )
    if ($Reload) {
        $taskServerArgs += '--reload'
    } else {
        $taskServerArgs += @('--workers', '1')
    }
    & uv @taskServerArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
