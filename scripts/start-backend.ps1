param([switch]$Reload, [switch]$ServeWeb)

$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
$taskPreviousServeWeb = [Environment]::GetEnvironmentVariable('CAPSTONE_SERVE_FRONTEND', 'Process')
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Please install uv and run uv sync --locked in backend first.'
}
if ($ServeWeb) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskRepoRoot 'frontend/dist/index.html') -PathType Leaf)) {
        throw 'Run pnpm.cmd build in frontend before starting with -ServeWeb.'
    }
}
Push-Location -LiteralPath (Join-Path $taskRepoRoot 'backend')
try {
    if ($ServeWeb) { $env:CAPSTONE_SERVE_FRONTEND = 'true' }
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
    if ($ServeWeb) {
        [Environment]::SetEnvironmentVariable('CAPSTONE_SERVE_FRONTEND', $taskPreviousServeWeb, 'Process')
    }
    Pop-Location
}
