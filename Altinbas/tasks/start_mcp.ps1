param()
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'RUNTIME_MISSING: run uv sync --locked --extra dev in the project first'
}
Set-Location -LiteralPath $projectPath
$env:PYTHONPATH = $projectPath
$env:PYTHONIOENCODING = 'utf-8'
& $pythonPath -B -m app.mcp.server
exit $LASTEXITCODE
