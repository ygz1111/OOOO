#!/usr/bin/env powershell
# ============================================================
# 智能电网负荷预测系统 - 一键停止脚本
# 用法: 在项目根目录运行  .\stop
# ============================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$ProcessStateFile = Join-Path $LogDir "smartgrid-processes.json"
$BackendPort = 8000
$FrontendPort = 3000

. (Join-Path $ProjectRoot 'scripts\process-runtime.ps1')

function Stop-SmartGridProcess(
    [int]$ProcessId,
    [string]$DisplayName,
    [string]$Role
) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return $false }

    if (-not (Test-SmartGridProcess $ProcessId $Role)) {
        Write-Host "  [$DisplayName] 跳过 PID $ProcessId：它不是本项目的 $Role 进程" -ForegroundColor Yellow
        return $false
    }

    if ($PSCmdlet.ShouldProcess("$DisplayName (PID: $ProcessId)", "停止本项目进程树")) {
        # /T 会同时关闭 npm/cmd 启动器及其 node 子进程。
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            Write-Host "  [$DisplayName] PID $ProcessId 未能停止，请检查当前运行权限" -ForegroundColor Yellow
            return $false
        }
        Write-Host "  [$DisplayName] 已停止 (PID: $ProcessId)" -ForegroundColor Green
        return $true
    }
    return $false
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  智能电网负荷预测系统 - 一键停止" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$state = $null
if (Test-Path -LiteralPath $ProcessStateFile) {
    try {
        $state = Get-Content -LiteralPath $ProcessStateFile -Raw | ConvertFrom-Json
        if ([string]$state.project_root -ne $ProjectRoot) {
            Write-Host "  [提示] 进程记录属于其他项目路径，将改用端口识别" -ForegroundColor Yellow
            $state = $null
        }
    }
    catch {
        Write-Host "  [提示] 进程记录无法读取，将改用端口识别" -ForegroundColor Yellow
        $state = $null
    }
}

$targets = @(
    [pscustomobject]@{
        Role = "frontend"
        Name = "前端"
        Port = $FrontendPort
        RecordedPids = if ($state) { @($state.frontend.launcher_pid, $state.frontend.listener_pid) } else { @() }
    },
    [pscustomobject]@{
        Role = "backend"
        Name = "后端"
        Port = $BackendPort
        RecordedPids = if ($state) { @($state.backend.launcher_pid, $state.backend.listener_pid) } else { @() }
    }
)

$stoppedAny = $false
$canRemoveProcessState = $true
foreach ($target in $targets) {
    # 先处理启动记录，再补充当前监听端口的进程，以兼容旧版 start 启动的服务。
    $candidatePids = @($target.RecordedPids) + @(Get-PortPids $target.Port)
    $candidatePids = @($candidatePids | Where-Object { $_ -and [int]$_ -gt 0 } | ForEach-Object { [int]$_ } | Sort-Object -Unique)

    if ($candidatePids.Count -eq 0) {
        Write-Host "  [$($target.Name)] 未运行（端口 $($target.Port) 空闲）" -ForegroundColor DarkGray
        continue
    }

    $roleStopped = $false
    foreach ($processId in $candidatePids) {
        if (Stop-SmartGridProcess $processId $target.Name $target.Role) {
            $roleStopped = $true
            $stoppedAny = $true
        }
        elseif (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            $canRemoveProcessState = $false
        }
    }

    Start-Sleep -Milliseconds 300
    $remaining = @(Get-PortPids $target.Port)
    if ($remaining.Count -gt 0) { $canRemoveProcessState = $false }
    if ($remaining.Count -eq 0) {
        Write-Host "  [$($target.Name)] 端口 $($target.Port) 已释放" -ForegroundColor Green
    }
    elseif (-not $roleStopped) {
        Write-Host "  [$($target.Name)] 端口仍被非本项目进程占用，未执行关闭" -ForegroundColor Yellow
    }
}

if (-not $WhatIfPreference -and $canRemoveProcessState -and (Test-Path -LiteralPath $ProcessStateFile)) {
    Remove-Item -LiteralPath $ProcessStateFile -Force
}

Write-Host ""
if ($WhatIfPreference) {
    Write-Host "  已完成模拟停止，未更改任何进程。" -ForegroundColor DarkGray
}
elseif ($stoppedAny -and $canRemoveProcessState) {
    Write-Host "  项目前后端已停止。" -ForegroundColor Green
}
elseif (-not $canRemoveProcessState) {
    Write-Host "  仍有进程或端口未释放，已保留启动记录。" -ForegroundColor Yellow
}
else {
    Write-Host "  没有发现正在运行的项目服务。" -ForegroundColor DarkGray
}
Write-Host ""
