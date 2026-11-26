#Requires -Version 7.0
param(
    [Parameter(Mandatory)]
    [ValidateSet('doctor', 'start', 'status', 'stop')]
    [string]$Action,
    [Parameter(Mandatory)]
    [string]$ConfigPath
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$config = (Resolve-Path -LiteralPath $ConfigPath).Path
$backend = Join-Path $root 'backend'
$statePath = $config + '.process.json'
$modulePattern = 'app\.modules\.compute\.desktop(?:\s|$)'
$configPattern = '--config\s+(?:"' + [regex]::Escape($config) + '"|' +
    [regex]::Escape($config) + '(?=\s|$))'
if (Test-Path -LiteralPath $statePath) {
    if ((Get-Item -LiteralPath $statePath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'NODE_STATE_ERROR'
    }
}
function Get-NodeProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and
        $_.CommandLine -match $modulePattern -and $_.CommandLine -match $configPattern
    })
}
function Read-OwnedSupervisor {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($saved.ConfigPath -ne $config -or $saved.SourceRoot -ne $root) {
        throw 'NODE_STATE_IDENTITY_MISMATCH'
    }
    $candidate = Get-Process -Id ([int]$saved.PID) -ErrorAction SilentlyContinue
    if (-not $candidate) { return $null }
    if ($candidate.StartTime.ToUniversalTime().Ticks.ToString() -ne $saved.StartTicks) {
        return $null
    }
    $info = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $candidate.Id)
    if ($info.ExecutablePath -ne $saved.UvExecutable -or
        $info.CommandLine -notmatch $modulePattern -or
        $info.CommandLine -notmatch $configPattern -or
        -not $info.CommandLine.Contains($backend)) {
        throw 'NODE_STATE_IDENTITY_MISMATCH'
    }
    return $candidate
}
if ($Action -eq 'doctor') {
    $uv = (Get-Command uv -ErrorAction Stop).Source
    & $uv run --directory $backend --frozen python -m app.modules.compute.doctor --config $config
    exit $LASTEXITCODE
}
# The same guard serializes launcher state writes and stop's identity check.
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($config.ToUpperInvariant()))
    $key = [BitConverter]::ToString($bytes).Replace('-', '')
} finally { $sha.Dispose() }
$guard = [Threading.Mutex]::new($false, ('Local\QaComputeNode-' + $key))
$acquired = $false
try {
    try { $acquired = $guard.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw 'NODE_COMMAND_BUSY' }
    if ($Action -eq 'status') {
        $supervisor = Read-OwnedSupervisor
        [pscustomobject]@{
            ProcessRunning = [bool]$supervisor
            SupervisorPID = if ($supervisor) { $supervisor.Id } else { $null }
            MatchingPythonProcesses = (Get-NodeProcesses).Count
            CloudOnlineConfirmed = $false
        } | ConvertTo-Json -Compress
        exit 0
    }
    if ($Action -eq 'stop') {
        $supervisor = Read-OwnedSupervisor
        if (-not $supervisor) {
            if ((Get-NodeProcesses).Count) { throw 'NODE_MANUAL_CHECK_REQUIRED' }
            Write-Output 'NODE_NOT_RUNNING'
            exit 0
        }
        $snapshot = @(Get-CimInstance Win32_Process)
        $ids = [Collections.Generic.HashSet[uint32]]::new()
        $null = $ids.Add([uint32]$supervisor.Id)
        do {
            $added = $false
            foreach ($process in $snapshot) {
                if ($ids.Contains([uint32]$process.ParentProcessId) -and
                    $ids.Add([uint32]$process.ProcessId)) { $added = $true }
            }
        } while ($added)
        $owned = @(Get-NodeProcesses | Where-Object { $ids.Contains([uint32]$_.ProcessId) })
        foreach ($process in $owned) {
            Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
        }
        if (-not $supervisor.HasExited) {
            Stop-Process -InputObject $supervisor -ErrorAction SilentlyContinue
        }
        Write-Output 'NODE_STOPPED_CHECK_MODEL_IDLE'
        exit 0
    }
    if ((Get-NodeProcesses).Count -or (Read-OwnedSupervisor)) { throw 'NODE_ALREADY_RUNNING' }
    $uv = (Get-Command uv -ErrorAction Stop).Source
    & $uv run --directory $backend --frozen python -m app.modules.compute.doctor --config $config
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $folder = Split-Path -Parent $config
    $outLog = Join-Path $folder ("node-$stamp.out.log")
    $errorLog = Join-Path $folder ("node-$stamp.err.log")
    $arguments = @('run', '--directory', ('"' + $backend + '"'), '--frozen',
        'python', '-m', 'app.modules.compute.desktop', '--config', ('"' + $config + '"'))
    $launch = @{
        FilePath = $uv
        ArgumentList = $arguments
        WorkingDirectory = $root
        WindowStyle = 'Hidden'
        RedirectStandardOutput = $outLog
        RedirectStandardError = $errorLog
        PassThru = $true
    }
    $process = Start-Process @launch
    $saved = [ordered]@{
        PID = $process.Id
        StartTicks = $process.StartTime.ToUniversalTime().Ticks.ToString()
        UvExecutable = $process.Path
        ConfigPath = $config
        SourceRoot = $root
        OutLog = $outLog
        ErrorLog = $errorLog
        AutoRestart = $false
    }
    [IO.File]::WriteAllText($statePath, ($saved | ConvertTo-Json))
    Write-Output 'NODE_PROCESS_STARTED'


} finally {
    if ($acquired) { $guard.ReleaseMutex() }
    $guard.Dispose()
}
