$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = 'E:\scf-env\venv\Scripts\python.exe'
$backendDir = Join-Path $repoRoot 'backend'

if (-not (Test-Path $python)) {
    throw "未找到虚拟环境解释器：$python。请先创建 venv 并安装 backend/requirements.txt。"
}

Push-Location $backendDir
try {
    # 启动前执行迁移，迁移已是最新时不做任何改动
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败，退出码 $LASTEXITCODE" }

    # 仅监听回环地址；--factory 使用 app.main:create_app
    & $python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
