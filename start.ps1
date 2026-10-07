#!/usr/bin/env powershell
# ============================================================
# 智能电网负荷预测系统 - 一键启动脚本
# 用法: 在项目根目录运行  .\start.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# 2026-08 修复: 用脚本自身目录定位项目根，支持任意路径/移动拷贝
$ProjectRoot = $PSScriptRoot
$BackendDir  = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$BackendPort = 8000
$FrontendPort = 3000
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$BackendStdout = Join-Path $LogDir "backend.stdout.log"
$BackendStderr = Join-Path $LogDir "backend.stderr.log"
$FrontendStdout = Join-Path $LogDir "frontend.stdout.log"
$FrontendStderr = Join-Path $LogDir "frontend.stderr.log"
$ProcessStateFile = Join-Path $LogDir "smartgrid-processes.json"

# 生产后端固定使用独立 TensorFlow 环境，避免误用 base/旧 Python 3.7 环境。
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    Write-Host "  [错误] 未找到 Conda，请先安装/初始化 Conda 后重试。" -ForegroundColor Red
    exit 1
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    Write-Host "  [错误] 未找到 npm，请先安装 Node.js 后重试。" -ForegroundColor Red
    exit 1
}

try {
    $CondaJson = conda env list --json | ConvertFrom-Json
}
catch {
    Write-Host "  [错误] 无法读取 Conda 环境列表：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$TfEnvPath = $CondaJson.envs | Where-Object {
    (Split-Path $_ -Leaf) -eq "smartgrid-tf"
} | Select-Object -First 1
if (-not $TfEnvPath) {
    Write-Host "  [错误] 未找到 Conda 环境 smartgrid-tf" -ForegroundColor Red
    Write-Host "  请先创建环境并安装 backend/requirements.txt" -ForegroundColor DarkGray
    exit 1
}
$BackendPython = Join-Path $TfEnvPath "python.exe"
if (-not (Test-Path -LiteralPath $BackendPython -PathType Leaf)) {
    Write-Host "  [错误] TensorFlow 环境缺少 Python：$BackendPython" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json") -PathType Leaf)) {
    Write-Host "  [错误] 前端 package.json 不存在：$FrontendDir" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  智能电网负荷预测系统 - 一键启动" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 辅助函数
# ============================================================

. (Join-Path $ProjectRoot 'scripts\process-runtime.ps1')

function Stop-PortProcess([int]$port, [string]$name, [string]$role) {
    $processIds = @(Get-PortPids $port)
    if ($processIds.Count -eq 0) {
        Write-Host "  [$name] 端口 $port 空闲" -ForegroundColor DarkGray
        return
    }

    $foreign = @($processIds | Where-Object { -not (Test-SmartGridProcess ([int]$_) $role) })
    if ($foreign.Count -gt 0) {
        $details = $foreign | ForEach-Object {
            $processName = (Get-Process -Id $_ -ErrorAction SilentlyContinue).ProcessName
            "PID $_ ($processName)"
        }
        throw "端口 $port 被非本项目进程占用：$($details -join ', ')。为避免误关程序，启动已停止。"
    }

    foreach ($processId in $processIds) {
        Write-Host "  [$name] 正在停止旧实例 (PID: $processId)..." -ForegroundColor Yellow
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    }
    Start-Sleep -Seconds 1
    if ((Get-PortPids $port).Count -gt 0) {
        throw "端口 $port 的旧实例未能停止，请运行 .\stop.ps1 后重试。"
    }
    Write-Host "  [$name] 端口 $port 已释放" -ForegroundColor Green
}

function Stop-StartedProcess([object]$Process, [string]$Name, [string]$Role) {
    if (-not $Process) { return }
    if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) {
        if (-not (Test-SmartGridProcess $Process.Id $Role)) {
            Write-Host "  [$Name] 无法核验 PID $($Process.Id) 的项目命令行，未执行关闭" -ForegroundColor Yellow
            return
        }
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
        if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) {
            Write-Host "  [$Name] 失败启动进程仍在运行 (PID: $($Process.Id))，请运行 .\stop.ps1" -ForegroundColor Yellow
        }
        else {
            Write-Host "  [$Name] 已清理失败启动的进程 (PID: $($Process.Id))" -ForegroundColor DarkGray
        }
    }
}

function Wait-BackendReady($port, [int]$LauncherId, $timeoutSec = 40) {
    $url = "http://localhost:$port/api/system/status"
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    $attempt = 0

    while ((Get-Date) -lt $deadline) {
        $attempt++
        if (-not (Get-Process -Id $LauncherId -ErrorAction SilentlyContinue)) {
            Write-Host "  后端启动进程已退出 (PID: $LauncherId)" -ForegroundColor Red
            return $false
        }
        # Check the listener before reading HTTP readiness; an old healthy server is not ours.
        if (-not (Test-StartedPortProcess $port $LauncherId 'backend')) {
            Start-Sleep -Seconds 2
            continue
        }
        try {
            $resp = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 3 -ErrorAction Stop
            if ($resp.status -eq "healthy") {
                Write-Host "  后端已就绪 (尝试 $attempt 次, 状态: healthy)" -ForegroundColor Green
                return $true
            }
        } catch {
            # 还没启动，继续等
        }
        Start-Sleep -Seconds 2
    }

    Write-Host "  后端在 ${timeoutSec}s 内未就绪" -ForegroundColor Red
    return $false
}

function Wait-FrontendReady($port, [int]$LauncherId, $timeoutSec = 60) {
    $url = "http://localhost:$port"
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    $attempt = 0

    while ((Get-Date) -lt $deadline) {
        $attempt++
        if (-not (Get-Process -Id $LauncherId -ErrorAction SilentlyContinue)) {
            Write-Host "  前端启动进程已退出 (PID: $LauncherId)" -ForegroundColor Red
            return $false
        }
        if (-not (Test-StartedPortProcess $port $LauncherId 'frontend')) {
            Start-Sleep -Seconds 2
            continue
        }
        try {
            # 用 curl.exe 避免 PowerShell Invoke-WebRequest 的 IE 引擎依赖和异常行为
            $output = curl.exe -s --connect-timeout 2 --max-time 3 -o NUL -w "%{http_code}" $url 2>$null
            if ($output -eq "200") {
                Write-Host "  前端已就绪 (尝试 $attempt 次)" -ForegroundColor Green
                return $true
            }
        } catch {
            # 还没启动，继续等
        }
        Start-Sleep -Seconds 2
    }

    Write-Host "  前端在 ${timeoutSec}s 内未就绪" -ForegroundColor Yellow
    return $false
}

# ============================================================
# 步骤 0: 运行 TensorFlow 生产资产检查
# ============================================================

Write-Host "[0/5] 检查运行资产..." -ForegroundColor Yellow
if (Test-Path (Join-Path $BackendDir "scripts\validate_tf_assets.py")) {
    & $BackendPython -X utf8 (Join-Path $BackendDir "scripts\validate_tf_assets.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  [错误] 运行资产缺失，请按上方指引恢复后再启动。" -ForegroundColor Red
        Write-Host "  提示: 请检查 TF weights.h5、Scaler JSON 和 Tail 验收资产。" -ForegroundColor DarkGray
        exit 1
    }
    Write-Host "  运行资产检查通过" -ForegroundColor Green
} else {
    Write-Host "  [警告] validate_tf_assets.py 不存在，跳过资产检查" -ForegroundColor Yellow
}

# ============================================================
# 步骤 1: 执行幂等数据库迁移
# ============================================================

Write-Host "[1/5] 检查数据库结构..." -ForegroundColor Yellow
$MigrateScript = Join-Path $BackendDir "scripts\migrate.py"
if (-not (Test-Path -LiteralPath $MigrateScript -PathType Leaf)) {
    Write-Host "  [错误] 数据库迁移脚本不存在：$MigrateScript" -ForegroundColor Red
    exit 1
}
& $BackendPython -X utf8 $MigrateScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [错误] 数据库迁移未完整完成，已停止启动。" -ForegroundColor Red
    Write-Host "  请检查 MySQL 是否运行，以及 .env 中 MYSQL_* 配置是否正确。" -ForegroundColor DarkGray
    exit 1
}
Write-Host "  数据库结构检查通过" -ForegroundColor Green

# ============================================================
# 步骤 2: 清理旧进程
# ============================================================

Write-Host "[2/5] 清理旧进程..." -ForegroundColor Yellow
try {
    Stop-PortProcess $BackendPort  "后端" "backend"
    Stop-PortProcess $FrontendPort "前端" "frontend"
}
catch {
    Write-Host "  [错误] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ============================================================
# 步骤 3: 启动后端
# ============================================================

Write-Host ""
Write-Host "[3/5] 启动后端 (端口 $BackendPort)..." -ForegroundColor Yellow

$backend = Start-Process -FilePath $BackendPython `
    -ArgumentList "-X", "utf8", "-m", "uvicorn", "realtime_api.app:app", "--app-dir", ('"{0}"' -f $BackendDir), "--host", "127.0.0.1", "--port", "$BackendPort" `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $BackendStdout `
    -RedirectStandardError $BackendStderr `
    -PassThru

Write-Host "  后端进程已创建 (PID: $($backend.Id))" -ForegroundColor DarkGray
Write-Host "  等待后端初始化..." -ForegroundColor DarkGray

try {
    $backendReady = Wait-BackendReady $BackendPort $backend.Id 40
}
catch {
    Write-Host "  [错误] $($_.Exception.Message)" -ForegroundColor Red
    $backendReady = $false
}

if (-not $backendReady) {
    Stop-StartedProcess $backend "后端" 'backend'
    Write-Host ""
    Write-Host "  [错误] 后端启动失败！请检查 $BackendStderr" -ForegroundColor Red
    Write-Host "  常见原因:" -ForegroundColor DarkGray
    Write-Host "    - Python 依赖未安装 (pip install -r backend/requirements.txt)" -ForegroundColor DarkGray
    Write-Host "    - 模型文件缺失" -ForegroundColor DarkGray
    Write-Host "    - 数据库连接失败" -ForegroundColor DarkGray
    exit 1
}

# ============================================================
# 步骤 4: 启动前端
# ============================================================

Write-Host ""
Write-Host "[4/5] 启动前端 (端口 $FrontendPort)..." -ForegroundColor Yellow

try {
    $frontend = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev", "--", "--strictPort" `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendStdout `
        -RedirectStandardError $FrontendStderr `
        -PassThru
}
catch {
    Stop-StartedProcess $backend "后端" 'backend'
    Write-Host "  [错误] 无法创建前端启动进程：$($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path -LiteralPath $ProcessStateFile) {
        Remove-Item -LiteralPath $ProcessStateFile -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

Write-Host "  前端进程已创建 (PID: $($frontend.Id))" -ForegroundColor DarkGray
Write-Host "  等待前端编译..." -ForegroundColor DarkGray

try {
    $frontendReady = Wait-FrontendReady $FrontendPort $frontend.Id 30
}
catch {
    Write-Host "  [错误] $($_.Exception.Message)" -ForegroundColor Red
    $frontendReady = $false
}

if (-not $frontendReady) {
    Stop-StartedProcess $frontend "前端" 'frontend'
    Stop-StartedProcess $backend "后端" 'backend'
    Write-Host ""
    Write-Host "  [错误] 前端启动失败，请检查 $FrontendStderr" -ForegroundColor Red
    if (Test-Path -LiteralPath $ProcessStateFile) {
        Remove-Item -LiteralPath $ProcessStateFile -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

# 保存本次启动的进程信息，供 .\stop 精确关闭本项目服务。
# 前端的 Start-Process PID 是 npm/cmd 启动器，真正监听端口的是其 node 子进程，
# 因此两者都记录；stop.ps1 会再次核验命令行，避免 PID 被复用时误关其他程序。
$processState = [ordered]@{
    project_root = $ProjectRoot
    started_at = (Get-Date).ToString("o")
    backend = [ordered]@{
        launcher_pid = $backend.Id
        listener_pid = @(Get-PortPids $BackendPort | Select-Object -First 1)[0]
        port = $BackendPort
    }
    frontend = [ordered]@{
        launcher_pid = $frontend.Id
        listener_pid = @(Get-PortPids $FrontendPort | Select-Object -First 1)[0]
        port = $FrontendPort
    }
}
$processState | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ProcessStateFile -Encoding UTF8

# ============================================================
# 步骤 5: 验证前后端联通
# ============================================================

Write-Host ""
Write-Host "[5/5] 验证前后端联通..." -ForegroundColor Yellow

try {
    # 通过前端代理访问后端 API（模拟浏览器行为）
    $proxyUrl = "http://localhost:$FrontendPort/api/system/status"
    $resp = Invoke-RestMethod -Uri $proxyUrl -Method GET -TimeoutSec 10 -ErrorAction Stop
    if ($resp.status -eq "healthy") {
        Write-Host "  前端代理 -> 后端 API 联通正常" -ForegroundColor Green
    }
} catch {
    Write-Host "  [警告] 前端代理测试失败，但服务可能仍在启动中" -ForegroundColor Yellow
    Write-Host "  请稍后手动访问 http://localhost:$FrontendPort 验证" -ForegroundColor DarkGray
}

# ============================================================
# 完成
# ============================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  启动完成!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  前端页面:   http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "  后端 API:   http://localhost:$BackendPort" -ForegroundColor White
Write-Host "  API 文档:   http://localhost:$BackendPort/docs" -ForegroundColor White
Write-Host ""
Write-Host "  日志目录:   $LogDir" -ForegroundColor DarkGray
Write-Host "  关闭服务:   .\stop.ps1" -ForegroundColor White
Write-Host ""
