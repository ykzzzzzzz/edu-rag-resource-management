# 启动前端开发服务器（Vite，127.0.0.1:5173，/api/v1 代理到后端 127.0.0.1:8000）。
# 路径相对于本脚本位置推导，不依赖固定的绝对路径。
$ErrorActionPreference = 'Stop'

$frontendDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'package.json'))) {
    throw "未找到前端项目：$frontendDir"
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules'))) {
    Write-Host '未检测到 node_modules，先执行 npm ci。'
    Push-Location $frontendDir
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci 失败，退出码 $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

Push-Location $frontendDir
try {
    npm run dev
    if ($LASTEXITCODE -ne 0) { throw "npm run dev 退出码 $LASTEXITCODE" }
} finally {
    Pop-Location
}
