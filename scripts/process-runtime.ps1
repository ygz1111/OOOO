# Shared read-only port/process checks for start.ps1 and stop.ps1.
# A failed query must not be treated as an unused port or a trusted project process.

function Get-PortPids([int]$Port) {
    try {
        $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
        if ($connections.Count -gt 0) {
            return @($connections.OwningProcess | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
        }
    }
    catch {
        # CIM/network inspection can be denied on Windows; netstat needs no CIM access.
    }

    # Do not use -p tcp: on Windows it can omit TCPv6 listeners (Vite's localhost).
    $rows = @(& netstat.exe -ano 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "无法检查端口 $Port 的监听进程（系统查询与 netstat 均不可用）。"
    }
    $listeners = foreach ($row in $rows) {
        if ($row -match '^\s*TCP\s+(\S+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
            $localAddress = $Matches[1]
            $listenerId = [int]$Matches[2]
            if ($localAddress -match (':' + $Port + '$') -and $listenerId -gt 0) {
                $listenerId
            }
        }
    }
    return @($listeners | Sort-Object -Unique)
}

function Get-SmartGridInspectorPython {
    if ($script:SmartGridInspectorPythonResolved) { return $script:SmartGridInspectorPython }
    $script:SmartGridInspectorPythonResolved = $true
    if ($BackendPython -and (Test-Path -LiteralPath $BackendPython -PathType Leaf)) {
        $script:SmartGridInspectorPython = $BackendPython
        return $script:SmartGridInspectorPython
    }
    try {
        if (Get-Command conda -ErrorAction SilentlyContinue) {
            $environments = & conda env list --json | ConvertFrom-Json
            $environmentPath = $environments.envs | Where-Object {
                (Split-Path $_ -Leaf) -eq 'smartgrid-tf'
            } | Select-Object -First 1
            if ($environmentPath) {
                $candidate = Join-Path $environmentPath 'python.exe'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    $script:SmartGridInspectorPython = $candidate
                }
            }
        }
    }
    catch {
        # No process identity means refusing to stop it; never weaken authentication here.
    }
    return $script:SmartGridInspectorPython
}

function Get-SmartGridProcessInfo([int]$ProcessId) {
    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        if ($process -and -not [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) {
            # npm/cmd launchers lack a path in their command line; psutil also provides cwd.
            if ([string]$process.CommandLine -match [regex]::Escape($ProjectRoot)) { return $process }
        }
    }
    catch {
        $process = $null
    }

    $inspectorPython = Get-SmartGridInspectorPython
    if ($inspectorPython) {
        try {
            $inspectionScript = Join-Path $ProjectRoot 'scripts\process-inspect.py'
            $result = & $inspectorPython -X utf8 $inspectionScript $ProcessId 2>$null
            if ($LASTEXITCODE -eq 0 -and $result) { return ($result | ConvertFrom-Json) }
        }
        catch {
            # The caller must reject a process without inspectable command-line evidence.
        }
    }
    return $process
}

function Get-ProcessCommandLine([int]$ProcessId) {
    $process = Get-SmartGridProcessInfo $ProcessId
    if (-not $process) { return $null }
    return [string]$process.CommandLine
}

function Test-SmartGridProcess([int]$ProcessId, [string]$Role) {
    $process = Get-SmartGridProcessInfo $ProcessId
    if (-not $process) { return $false }
    $commandLine = [string]$process.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) { return $false }
    $roleMatches = if ($Role -eq 'backend') {
        $commandLine -match '(?i)uvicorn' -and $commandLine -match 'realtime_api\.app:app'
    } elseif ($Role -eq 'frontend') {
        $commandLine -match "(?i)(vite(?:\.js)?|npm(?:\.cmd)?[`"']?\s+run\s+dev)"
    } else { $false }
    if (-not $roleMatches) { return $false }

    $root = $ProjectRoot.TrimEnd('\', '/')
    $rootPattern = [regex]::Escape($root) + '(?:[\\/]|["''\s]|$)'
    if ($commandLine -match $rootPattern) { return $true }
    # Require both the expected command and this project's cwd, even for recorded PIDs.
    # This also prevents a recycled PID from authorizing another project's server.
    $workingDirectory = [string]$process.WorkingDirectory
    return $workingDirectory.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $workingDirectory.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-StartedPortProcess([int]$Port, [int]$LauncherId, [string]$Role) {
    $listeners = @(Get-PortPids $Port)
    if ($listeners.Count -eq 0) { return $false }
    foreach ($listenerId in $listeners) {
        if (-not (Test-SmartGridProcess $listenerId $Role)) {
            throw "端口 $Port 的监听进程 PID $listenerId 不属于本项目，不能确认本次启动成功。"
        }
        $ancestorId = [int]$listenerId
        $belongsToLaunch = $false
        for ($depth = 0; $depth -lt 16 -and $ancestorId -gt 0; $depth++) {
            if ($ancestorId -eq $LauncherId) { $belongsToLaunch = $true; break }
            $process = Get-SmartGridProcessInfo $ancestorId
            if (-not $process) { break }
            $ancestorId = [int]$process.ParentProcessId
        }
        if (-not $belongsToLaunch) {
            throw "端口 $Port 仍由旧实例或其他启动进程 PID $listenerId 占用，本次启动不能复用其就绪响应。"
        }
    }
    return $true
}
