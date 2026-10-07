# Focused, read-only regression checks; no service is started or stopped.
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent

# Windows PowerShell 5.1 reads BOM-less scripts using the local ANSI code page.
# Guard all startup scripts even when this regression runs under PowerShell 7.
foreach ($relativePath in @('start.ps1', 'stop.ps1', 'scripts\process-runtime.ps1')) {
    $scriptPath = Join-Path $ProjectRoot $relativePath
    $scriptBytes = [System.IO.File]::ReadAllBytes($scriptPath)
    $hasBom = $scriptBytes.Length -ge 3 -and
        $scriptBytes[0] -eq 0xEF -and $scriptBytes[1] -eq 0xBB -and $scriptBytes[2] -eq 0xBF
    if (@($scriptBytes | Where-Object { $_ -gt 127 }).Count -gt 0 -and -not $hasBom) {
        throw "$relativePath contains non-ASCII text and requires UTF-8 BOM for Windows PowerShell 5.1."
    }
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        throw "$relativePath has parse errors: $($parseErrors.ErrorId -join ', ')"
    }
}

. (Join-Path $PSScriptRoot 'process-runtime.ps1')

function Assert-ProcessCheck([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

# Force the restricted-CIM path and control netstat output without touching real sockets.
function Get-NetTCPConnection { throw 'CIM access denied' }
$script:NetstatExitCode = 0
$script:NetstatRows = @(
    '  TCP    127.0.0.1:8000     0.0.0.0:0    LISTENING    101',
    '  TCP    [::1]:3000         [::]:0       LISTENING    202',
    '  TCP    127.0.0.1:6000     1.2.3.4:3000 ESTABLISHED  303'
)
function netstat.exe {
    $global:LASTEXITCODE = $script:NetstatExitCode
    return $script:NetstatRows
}
Assert-ProcessCheck ((@(Get-PortPids 8000) -join ',') -eq '101') 'IPv4 listener fallback failed'
Assert-ProcessCheck ((@(Get-PortPids 3000) -join ',') -eq '202') 'IPv6 listener fallback failed'
Assert-ProcessCheck (@(Get-PortPids 6000).Count -eq 0) 'Established connection was treated as a listener'
$script:NetstatExitCode = 1
$queryFailed = $false
try { Get-PortPids 8000 | Out-Null } catch { $queryFailed = $true }
Assert-ProcessCheck $queryFailed 'Failed queries were treated as an unused port'
$script:NetstatExitCode = 0

$script:ProcessInfos = @{
    101 = [pscustomobject]@{CommandLine="python -m uvicorn realtime_api.app:app --app-dir `"$ProjectRoot\backend`""; ParentProcessId=1}
    202 = [pscustomobject]@{CommandLine="node `"$ProjectRoot\frontend\node_modules\vite\bin\vite.js`""; ParentProcessId=201}
    201 = [pscustomobject]@{CommandLine='cmd /c npm.cmd run dev'; WorkingDirectory="$ProjectRoot\frontend"; ParentProcessId=1}
    404 = [pscustomobject]@{CommandLine='python -m uvicorn realtime_api.app:app --app-dir D:\OtherProject\backend'; ParentProcessId=1}
    405 = [pscustomobject]@{CommandLine=''; WorkingDirectory=$ProjectRoot; ParentProcessId=1}
    406 = [pscustomobject]@{CommandLine="python -m uvicorn realtime_api.app:app --app-dir $ProjectRoot-other\backend"; ParentProcessId=1}
}
function Get-SmartGridProcessInfo([int]$ProcessId) { return $script:ProcessInfos[$ProcessId] }
Assert-ProcessCheck (Test-SmartGridProcess 101 'backend') 'Current project backend was rejected'
Assert-ProcessCheck (Test-SmartGridProcess 201 'frontend') 'Project npm launcher cwd was rejected'
Assert-ProcessCheck (-not (Test-SmartGridProcess 404 'backend')) 'Foreign backend was trusted'
Assert-ProcessCheck (-not (Test-SmartGridProcess 405 'backend')) 'Missing command line was trusted'
Assert-ProcessCheck (-not (Test-SmartGridProcess 406 'backend')) 'Sibling path was trusted'
Assert-ProcessCheck (Test-StartedPortProcess 8000 101 'backend') 'New backend listener was rejected'
Assert-ProcessCheck (Test-StartedPortProcess 3000 201 'frontend') 'New frontend child listener was rejected'
$oldListenerRejected = $false
try { Test-StartedPortProcess 8000 404 'backend' | Out-Null } catch { $oldListenerRejected = $true }
Assert-ProcessCheck $oldListenerRejected 'Old server could satisfy new launch readiness'
Assert-ProcessCheck (-not (Test-StartedPortProcess 9000 101 'backend')) 'Unbound new process was considered ready'
Write-Output 'All process-runtime regression checks passed (no services changed).'
