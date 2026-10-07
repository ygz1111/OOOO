# Isolated launcher checks: no application, database or HTTP service is started.
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$tokens = $null
$parseErrors = $null
$startupAst = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $ProjectRoot 'start.ps1'), [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { throw 'Startup script does not parse.' }

function Assert-StartupCheck([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$backendAssignment = $startupAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq '$backend' -and
        $node.Right.Extent.Text -match 'Start-Process'
}, $true)
Assert-StartupCheck ($null -ne $backendAssignment) 'Backend launcher assignment missing.'
$BackendDir = 'D:\GitHub\Smart Grid\backend'
$BackendPython = $PythonPath
$BackendPort = 8000
$BackendStdout = 'unused.stdout'
$BackendStderr = 'unused.stderr'
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru)
    $script:CapturedArguments = $ArgumentList
    return [pscustomobject]@{Id = 123}
}
Invoke-Expression $backendAssignment.Extent.Text
$appDirIndex = [array]::IndexOf($script:CapturedArguments, '--app-dir')
Assert-StartupCheck ($appDirIndex -ge 0) 'Backend --app-dir missing.'
$quotedAppDir = $script:CapturedArguments[$appDirIndex + 1]
Assert-StartupCheck ($quotedAppDir -eq ('"{0}"' -f $BackendDir)) 'Path containing spaces is unquoted.'

$taskDir = Join-Path $ProjectRoot ('.codex_tmp\startup-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
$probePath = Join-Path $taskDir 'argv.py'
$probeOutput = Join-Path $taskDir 'argv.json'
$failurePath = Join-Path $taskDir 'failure.ps1'
$failureOutput = Join-Path $taskDir 'cleanup.txt'
$fakeStatePath = Join-Path $taskDir 'state.json'
try {
    if ($PythonPath) {
        # Exercise the real Windows argument joiner using a disposable Python process.
        [System.IO.File]::WriteAllText($probePath, 'import json, sys; print(json.dumps(sys.argv[1:]))')
        Microsoft.PowerShell.Management\Start-Process -FilePath $PythonPath `
            -ArgumentList '-X', 'utf8', ('"{0}"' -f $probePath), '--app-dir', $quotedAppDir `
            -WindowStyle Hidden -RedirectStandardOutput $probeOutput -Wait
        $received = Get-Content -LiteralPath $probeOutput -Raw | ConvertFrom-Json
        Assert-StartupCheck ($received.Count -eq 2 -and $received[1] -eq $BackendDir) 'Windows split a spaced path.'
    }

    $frontendTry = $startupAst.Find({
        param($node)
        $node -is [System.Management.Automation.Language.TryStatementAst] -and
            $node.Body.Extent.Text -match '\$frontend\s*=\s*Start-Process'
    }, $true)
    Assert-StartupCheck ($null -ne $frontendTry) 'Frontend launcher has no exception cleanup.'
    $childPrelude = @'
$ErrorActionPreference = 'Stop'
$taskDir = $PSScriptRoot
$ProcessStateFile = Join-Path $taskDir 'state.json'
$backend = [pscustomobject]@{Id=123}
$FrontendDir = 'unused'
$FrontendStdout = 'unused'
$FrontendStderr = 'unused'
function Start-Process { throw 'simulated launcher failure' }
function Stop-StartedProcess {
    param($Process, $Name, $Role)
    if ($Process.Id -ne 123 -or $Role -ne 'backend') { throw 'Wrong cleanup target.' }
    [System.IO.File]::WriteAllText((Join-Path $taskDir 'cleanup.txt'), 'backend-cleaned')
}
'@
    [System.IO.File]::WriteAllText($fakeStatePath, '{}')
    [System.IO.File]::WriteAllText($failurePath, $childPrelude + "`n" + $frontendTry.Extent.Text,
        (New-Object System.Text.UTF8Encoding($true)))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $failurePath | Out-Null
    Assert-StartupCheck ($LASTEXITCODE -eq 1) 'Launcher failure was reported as success.'
    Assert-StartupCheck ((Get-Content -LiteralPath $failureOutput -Raw) -eq 'backend-cleaned') 'Backend cleanup missing.'
    Assert-StartupCheck (-not (Test-Path -LiteralPath $fakeStatePath)) 'Failed launch left stale process state.'

    $frontendWait = $startupAst.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Wait-FrontendReady'
    }, $true)
    Assert-StartupCheck ($frontendWait.Extent.Text -match 'curl\.exe[^\r\n]*--max-time 3') 'Frontend HTTP probe can wait indefinitely.'
    Write-Output 'All startup-runtime checks passed (application remains stopped).'
}
finally {
    # Only remove the explicitly created disposable files, never a process or data directory.
    foreach ($file in @($probePath, $probeOutput, $failurePath, $failureOutput, $fakeStatePath)) {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
    if (Test-Path -LiteralPath $taskDir) { Remove-Item -LiteralPath $taskDir }
}
