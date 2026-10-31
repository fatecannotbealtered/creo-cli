#requires -Version 7.4
<# Internal process/log host for start-owned-creo.ps1. No CAD or desktop API.
The separate host retains inherited output pipes until their natural closure, so
the bounded startup checker can finish without killing a launcher or dropping logs.
#>
param([Parameter(Mandatory)][string]$LaunchSpecPath)
$ErrorActionPreference = 'Stop'

function Save-ProcessRecord([string]$Path, $Value) {
    $temporary = $Path + '.writing'
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 12) + "`n")
    $file = [System.IO.FileStream]::new($temporary, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try { $file.Write($bytes, 0, $bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
    [System.IO.File]::Move($temporary, $Path, $false)
}

$spec = Get-Content -LiteralPath $LaunchSpecPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
$stdout = $null; $stderr = $null; $process = $null
try {
    $stdout = [System.IO.FileStream]::new($spec.stdout, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $stderr = [System.IO.FileStream]::new($spec.stderr, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $spec.executable; $start.WorkingDirectory = $spec.working_directory
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    foreach ($key in @($start.Environment.Keys)) {
        if ($key -like 'CREO_CLI_*' -or $key -in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE')) { [void]$start.Environment.Remove($key) }
    }
    foreach ($key in $spec.environment.Keys) { $start.Environment[$key] = [string]$spec.environment[$key] }
    foreach ($argument in $spec.arguments) { $start.ArgumentList.Add([string]$argument) }
    $process = [System.Diagnostics.Process]::new(); $process.StartInfo = $start
    [void]$process.Start()
    $stdoutCopy = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
    $stderrCopy = $process.StandardError.BaseStream.CopyToAsync($stderr)
    $created = $null
    try { $created = [string]$process.StartTime.ToUniversalTime().ToFileTimeUtc() } catch { }
    Save-ProcessRecord $spec.process_record ([ordered]@{
        launcher_pid = $process.Id; launcher_creation_filetime = $created; process_host_pid = $PID
        executable = $spec.executable; arguments = $spec.arguments; started_at_utc = [DateTime]::UtcNow.ToString('o')
        input_method = 'ProcessStartInfo.ArgumentList'; desktop_inputs = 0; CUA_inputs = 0
    })
    # This is the explicitly owned process host, not the bounded checker. It waits
    # without polling for natural exits and does not terminate any process.
    $process.WaitForExit()
    [System.Threading.Tasks.Task]::WhenAll([System.Threading.Tasks.Task[]]@($stdoutCopy, $stderrCopy)).GetAwaiter().GetResult()
    $stdout.Flush($true); $stderr.Flush($true)
    Save-ProcessRecord $spec.completion_record ([ordered]@{
        status = 'launcher_and_output_streams_finished'; launcher_pid = $process.Id
        exit_code = $process.ExitCode; finished_at_utc = [DateTime]::UtcNow.ToString('o'); processes_killed = @()
    })
} catch {
    Save-ProcessRecord $spec.error_record ([ordered]@{
        status = 'process_host_failed'; error_type = $_.Exception.GetType().FullName
        observed_at_utc = [DateTime]::UtcNow.ToString('o'); processes_killed = @()
    })
    exit 1
} finally {
    if ($null -ne $stdout) { $stdout.Dispose() }
    if ($null -ne $stderr) { $stderr.Dispose() }
    if ($null -ne $process) { $process.Dispose() }
}
