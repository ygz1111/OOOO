#!/usr/bin/env powershell
# ============================================================
# 智能电网负荷预测系统 - 一键启动脚本
# 用法: 在项目根目录运行  .\start.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\GitHub\OOOOOO"
$BackendDir  = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$BackendPort = 8000
$FrontendPort = 3000

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  智能电网负荷预测系统 - 一键启动" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 辅助函数
# ============================================================

function Get-PortPid($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return $conn.OwningProcess | Select-Object -First 1 }
    return $null
}

function Stop-PortProcess($port, $name) {
    $procId = Get-PortPid $port
    if ($procId) {
        $procName = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
        Write-Host "  [$name] 端口 $port 被 $procName (PID: $procId) 占用，正在终止..." -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        # 确认已释放
        if (Get-PortPid $port) {
            Write-Host "  [$name] 端口 $port 仍被占用，尝试 taskkill..." -ForegroundColor Yellow
            taskkill /PID $procId /T /F 2>$null | Out-Null
            Start-Sleep -Seconds 1
        }
        Write-Host "  [$name] 端口 $port 已释放" -ForegroundColor Green
    } else {
        Write-Host "  [$name] 端口 $port 空闲" -ForegroundColor DarkGray
    }
}

function Wait-BackendReady($port, $timeoutSec = 40) {
    $url = "http://localhost:$port/api/system/status"
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    $attempt = 0

    while ((Get-Date) -lt $deadline) {
        $attempt++
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

function Wait-FrontendReady($port, $timeoutSec = 60) {
    $url = "http://localhost:$port"
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    $attempt = 0

    while ((Get-Date) -lt $deadline) {
        $attempt++
        try {
            # 用 curl.exe 避免 PowerShell Invoke-WebRequest 的 IE 引擎依赖和异常行为
            $output = curl.exe -s -o NUL -w "%{http_code}" $url 2>$null
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
# 步骤 0: 清理旧进程
# ============================================================

Write-Host "[0/3] 清理旧进程..." -ForegroundColor Yellow
Stop-PortProcess $BackendPort  "后端"
Stop-PortProcess $FrontendPort "前端"

# ============================================================
# 步骤 1: 启动后端
# ============================================================

Write-Host ""
Write-Host "[1/3] 启动后端 (端口 $BackendPort)..." -ForegroundColor Yellow

$backend = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "realtime_api.app:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--reload" `
    -WorkingDirectory $BackendDir `
    -WindowStyle Normal `
    -PassThru

Write-Host "  后端进程已创建 (PID: $($backend.Id))" -ForegroundColor DarkGray
Write-Host "  等待后端初始化..." -ForegroundColor DarkGray

$backendReady = Wait-BackendReady $BackendPort 40

if (-not $backendReady) {
    Write-Host ""
    Write-Host "  [错误] 后端启动失败！请检查后端窗口的错误信息。" -ForegroundColor Red
    Write-Host "  常见原因:" -ForegroundColor DarkGray
    Write-Host "    - Python 依赖未安装 (pip install -r backend/requirements.txt)" -ForegroundColor DarkGray
    Write-Host "    - 模型文件缺失" -ForegroundColor DarkGray
    Write-Host "    - 数据库连接失败" -ForegroundColor DarkGray
    exit 1
}

# ============================================================
# 步骤 2: 启动前端
# ============================================================

Write-Host ""
Write-Host "[2/3] 启动前端 (端口 $FrontendPort)..." -ForegroundColor Yellow

$frontend = Start-Process -FilePath "cmd" `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Normal `
    -PassThru

Write-Host "  前端进程已创建 (PID: $($frontend.Id))" -ForegroundColor DarkGray
Write-Host "  等待前端编译..." -ForegroundColor DarkGray

$frontendReady = Wait-FrontendReady $FrontendPort 30

if (-not $frontendReady) {
    Write-Host ""
    Write-Host "  [警告] 前端可能仍在编译中，请稍等片刻后手动访问。" -ForegroundColor Yellow
}

# ============================================================
# 步骤 3: 验证前后端联通
# ============================================================

Write-Host ""
Write-Host "[3/3] 验证前后端联通..." -ForegroundColor Yellow

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
Write-Host "  关闭服务: 关闭弹出的两个终端窗口即可" -ForegroundColor DarkGray
Write-Host ""
