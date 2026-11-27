# 一键启动：检查数据库，然后各开一个窗口运行后端和前端。
# 用法（Windows PowerShell 5.1 或 PowerShell 7 都可以）：
#   powershell -File .\scripts\start-all.ps1
# 加 -WithIndexer 同时开启索引进程（审核通过的资料靠它变成"可用于问答"）。
param(
    [switch]$WithIndexer
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pgCtl = 'E:\scf-env\postgres\Library\bin\pg_ctl.exe'
$pgData = 'E:\scf-env\pgdata'
$pgLog = 'E:\scf-env\postgres.log'
$pgPort = 55432

function Test-Port([int]$Port) {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Start-Window([string]$Title, [string]$ScriptName, [string]$ExtraArgs = '') {
    $script = Join-Path $PSScriptRoot $ScriptName
    # -NoExit：脚本出错或结束后窗口保持打开，错误信息不会一闪而过。
    $command = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$repoRoot'; & '$script' $ExtraArgs"
    Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-NoExit', '-Command', $command | Out-Null
}

Write-Host '检查数据库 ...'
if (-not (Test-Port $pgPort)) {
    if (-not (Test-Path -LiteralPath $pgCtl)) {
        throw "找不到 pg_ctl：$pgCtl。请确认 PostgreSQL 已安装。"
    }
    Write-Host "数据库没有运行，正在启动（端口 $pgPort）..."
    & $pgCtl -D $pgData -l $pgLog -o "-h 127.0.0.1 -p $pgPort" -w start
    if ($LASTEXITCODE -ne 0) { throw "数据库启动失败，请查看 $pgLog" }
}
Write-Host "数据库已在端口 $pgPort 运行。"

if (Test-Port 8000) {
    Write-Host '后端端口 8000 已被占用，跳过后端（可能已经在运行）。'
} else {
    Write-Host '正在打开后端窗口 ...'
    Start-Window '启明学堂 后端' 'start-api.ps1'
}

if (Test-Port 5173) {
    Write-Host '前端端口 5173 已被占用，跳过前端（可能已经在运行）。'
} else {
    Write-Host '正在打开前端窗口 ...'
    Start-Window '启明学堂 前端' 'start-web.ps1'
}

if ($WithIndexer) {
    Write-Host '正在打开索引进程窗口 ...'
    Start-Window '启明学堂 索引进程' 'start-indexer.ps1'
}

Write-Host ''
Write-Host '启动命令已发出。后端首次加载检索模型约需 1 分钟，期间问答会提示"检索模型正在加载"。'
Write-Host '浏览器打开：http://127.0.0.1:5173'
Write-Host '演示账号：admin、teacher01、student01，密码在 data\local\demo-accounts.txt。'
Write-Host '要停止服务，直接关闭对应的窗口。'
