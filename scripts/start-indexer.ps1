$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = 'E:\scf-env\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw '未找到项目虚拟环境，请先安装后端依赖。'
}

Push-Location (Join-Path $repoRoot 'backend')
try {
    & $python -m app.index_worker @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
