#requires -Version 7.4
<#
Dot-source this file. Requires only the packaged EXE and PowerShell, never Python.
The caller declares the continuing history and owned service generation. This helper
never creates/replaces history, changes permission, selects a different instance,
replays a confirmation, or kills a timed-out CLI/CAD process. Keep the PowerShell
host alive while pending stream-copy tasks finish; pending evidence remains pending.
Raw preview stdout contains its short-lived confirm token: keep EvidenceDirectory
private. Metadata redacts tokens; no claim about Windows ACL isolation is made.
#>

function Write-CreoHelperJson {
    param([string]$Path, $Value, [switch]$CreateNew)
    $mode = if ($CreateNew) { [System.IO.FileMode]::CreateNew } else { [System.IO.FileMode]::Create }
    $stream = [System.IO.FileStream]::new($Path, $mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 24) + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Get-CreoHelperSafeArguments {
    param([string[]]$Arguments)
    $hideNext = $false
    foreach ($argument in $Arguments) {
        if ($hideNext) { '<redacted-confirm-token>'; $hideNext = $false }
        elseif ($argument -eq '--confirm') { $argument; $hideNext = $true }
        elseif ($argument -match '^--confirm=') { '--confirm=<redacted-confirm-token>' }
        else { $argument }
    }
}

function New-CreoCliRun {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ExecutablePath,
        [Parameter(Mandatory)][string]$EvidenceDirectory,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Environment,
        [ValidateRange(1, 86400)][int]$TimeoutSeconds = 360
    )
    foreach ($value in @($ExecutablePath, $EvidenceDirectory)) {
        if (-not [System.IO.Path]::IsPathFullyQualified($value)) { throw 'Use absolute EXE and evidence paths.' }
    }
    $executable = [System.IO.Path]::GetFullPath($ExecutablePath)
    $evidence = [System.IO.Path]::GetFullPath($EvidenceDirectory)
    if (-not [System.IO.File]::Exists($executable)) { throw 'The declared CLI executable is missing.' }
    $declared = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in $Environment.Keys) {
        if ([string]$key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or $null -eq $Environment[$key] -or
            ([string]$Environment[$key]).Contains([char]0)) { throw 'Invalid declared environment entry.' }
        $declared.Add([string]$key, [string]$Environment[$key])
    }
    foreach ($required in @('CREO_CLI_CONFIG_DIR', 'CREO_CLI_SERVICE_URL')) {
        if (-not $declared.ContainsKey($required) -or [string]::IsNullOrWhiteSpace($declared[$required])) {
            throw "Declare $required explicitly; inherited CLI selection is never used."
        }
    }
    $history = $declared['CREO_CLI_CONFIG_DIR']
    if (-not [System.IO.Path]::IsPathFullyQualified($history) -or -not [System.IO.Directory]::Exists($history)) {
        throw 'Declare the existing continuing history directory; this helper never creates a history directory.'
    }
    $endpoint = $null
    if (-not [uri]::TryCreate($declared['CREO_CLI_SERVICE_URL'], [System.UriKind]::Absolute, [ref]$endpoint) -or
        $endpoint.Scheme -ne 'http' -or $endpoint.Host -ne '127.0.0.1' -or
        $endpoint.Port -lt 1024 -or $endpoint.UserInfo -or $endpoint.Query -or $endpoint.Fragment -or $endpoint.AbsolutePath -ne '/') {
        throw 'Declare the exact owned http://127.0.0.1:port endpoint without credentials or URL parameters.'
    }
    [void][System.IO.Directory]::CreateDirectory($evidence)
    return [pscustomobject]@{
        PSTypeName = 'CreoCli.OwnedRun'
        ExecutablePath = $executable
        ExecutableSha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        EvidenceDirectory = $evidence
        Environment = $declared
        HistoryDirectory = [System.IO.Path]::GetFullPath($history)
        HistoryExistedBefore = $true
        TimeoutSeconds = $TimeoutSeconds
        Blocked = $false
        BlockReason = $null
        PendingInvocations = [System.Collections.Generic.List[object]]::new()
    }
}

function Invoke-CreoCliCore {
    param($Run, [string]$Label, [string[]]$Arguments, [int]$TimeoutSeconds, [switch]$LocalOperationShow)
    if ($Run.PSTypeNames -notcontains 'CreoCli.OwnedRun') { throw 'Use New-CreoCliRun to declare this execution.' }
    if ($Run.Blocked -and -not $LocalOperationShow) { throw 'This run is stopped. Inspect retained local evidence; no further CAD command is allowed.' }
    if ($Label -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$') { throw 'Use a unique simple ASCII evidence label.' }
    if ($null -eq $Arguments -or $Arguments.Count -eq 0 -or @($Arguments | Where-Object { $null -eq $_ -or $_.Contains([char]0) }).Count) {
        throw 'Pass command arguments as a nonempty string array without NUL characters.'
    }
    if ($TimeoutSeconds -le 0) { $TimeoutSeconds = $Run.TimeoutSeconds }
    $stdoutPath = Join-Path $Run.EvidenceDirectory ($Label + '.stdout.json')
    $stderrPath = Join-Path $Run.EvidenceDirectory ($Label + '.stderr.log')
    $metadataPath = Join-Path $Run.EvidenceDirectory ($Label + '.metadata.json')
    foreach ($path in @($stdoutPath, $stderrPath, $metadataPath)) {
        if (Test-Path -LiteralPath $path) { throw 'Evidence label already exists; original files are preserved.' }
    }
    $invocationArguments = @($Arguments) + @('--json', '--compact')
    $metadata = [ordered]@{
        label = $Label; state = 'prepared'; started_at_utc = [DateTime]::UtcNow.ToString('o')
        executable = $Run.ExecutablePath; executable_sha256 = $Run.ExecutableSha256
        arguments = @(Get-CreoHelperSafeArguments $invocationArguments)
        environment_names = @($Run.Environment.Keys | Sort-Object)
        continuing_history_directory = $Run.HistoryDirectory
        history_directory_created_by_helper = $false
        stdout = $stdoutPath; stderr = $stderrPath; metadata = $metadataPath
        process_timeout_seconds = $TimeoutSeconds; local_operation_show = [bool]$LocalOperationShow
        automatic_retry = $false; process_killed = $false; exit_code = $null
        preview_stdout_may_contain_confirm_token = $invocationArguments -contains '--dry-run'
    }
    Write-CreoHelperJson $metadataPath $metadata -CreateNew
    $stdoutStream = $null; $stderrStream = $null; $process = $null; $pending = $false
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $stdoutStream = [System.IO.FileStream]::new($stdoutPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        $stderrStream = [System.IO.FileStream]::new($stderrPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        $observedExecutableHash = (Get-FileHash -LiteralPath $Run.ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $metadata.observed_executable_sha256 = $observedExecutableHash
        if ($observedExecutableHash -ne $Run.ExecutableSha256) { throw 'The declared CLI bytes changed; preserve and inspect the candidate.' }
        $start = [System.Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $Run.ExecutablePath
        $start.UseShellExecute = $false; $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
        $start.WorkingDirectory = if ($Run.Environment.ContainsKey('CREO_CLI_WORKSPACE')) { $Run.Environment['CREO_CLI_WORKSPACE'] } else { $Run.HistoryDirectory }
        foreach ($key in @($start.Environment.Keys)) {
            if ($key -like 'CREO_CLI_*' -or $key -in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE')) { [void]$start.Environment.Remove($key) }
        }
        foreach ($key in $Run.Environment.Keys) { $start.Environment[$key] = $Run.Environment[$key] }
        foreach ($argument in $invocationArguments) { $start.ArgumentList.Add($argument) }
        $process = [System.Diagnostics.Process]::new(); $process.StartInfo = $start
        [void]$process.Start()
        $metadata.process_id = $process.Id
        $metadata.process_creation_filetime = [string]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
        $metadata.state = 'running'; Write-CreoHelperJson $metadataPath $metadata
        $stdoutTask = $process.StandardOutput.BaseStream.CopyToAsync($stdoutStream)
        $stderrTask = $process.StandardError.BaseStream.CopyToAsync($stderrStream)
        $copies = [System.Threading.Tasks.Task]::WhenAll([System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask))
        $remaining = [Math]::Max(0, [int]($TimeoutSeconds * 1000 - $clock.Elapsed.TotalMilliseconds))
        $exited = $process.WaitForExit($remaining)
        $remaining = [Math]::Max(0, [int]($TimeoutSeconds * 1000 - $clock.Elapsed.TotalMilliseconds))
        $copied = $exited -and $copies.Wait($remaining)
        if (-not $exited -or -not $copied) {
            $pending = $true; $Run.Blocked = $true; $Run.BlockReason = 'pending_cli_or_output_streams'
            $metadata.state = if ($exited) { 'process_exited_output_pending' } else { 'pending' }
            if ($exited) { $metadata.exit_code = $process.ExitCode }
            $metadata.observed_at_utc = [DateTime]::UtcNow.ToString('o')
            $metadata.duration_seconds = $clock.Elapsed.TotalSeconds
            $metadata.next_action = 'Keep this host and original CLI alive. Inspect only retained files or Get-CreoCliLocalOperation; do not dispatch further CAD or replay.'
            $Run.PendingInvocations.Add([pscustomobject]@{
                Label = $Label; Process = $process; StdoutStream = $stdoutStream; StderrStream = $stderrStream
                StdoutTask = $stdoutTask; StderrTask = $stderrTask; MetadataPath = $metadataPath
            })
            Write-CreoHelperJson $metadataPath $metadata
            throw "CLI invocation $Label is pending; no process was killed."
        }
        $stdoutStream.Flush($true); $stderrStream.Flush($true)
        $stdoutStream.Dispose(); $stdoutStream = $null
        $stderrStream.Dispose(); $stderrStream = $null
        $metadata.exit_code = $process.ExitCode
        $metadata.finished_at_utc = [DateTime]::UtcNow.ToString('o')
        $metadata.duration_seconds = $clock.Elapsed.TotalSeconds
        $metadata.state = 'finished'
        $metadata.stdout_sha256 = (Get-FileHash -LiteralPath $stdoutPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $metadata.stderr_sha256 = (Get-FileHash -LiteralPath $stderrPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $document = $null
        try {
            $raw = [System.IO.File]::ReadAllText($stdoutPath, [System.Text.UTF8Encoding]::new($false, $true))
            $document = ConvertFrom-Json -InputObject $raw -AsHashtable -Depth 100 -ErrorAction Stop
            if ($document -isnot [System.Collections.IDictionary] -or $document['ok'] -isnot [bool] -or
                [string]::IsNullOrWhiteSpace($document['schema_version'])) { throw 'Invalid CLI envelope.' }
        } catch {
            $Run.Blocked = $true; $Run.BlockReason = 'invalid_cli_response'
            $metadata.response_valid = $false; Write-CreoHelperJson $metadataPath $metadata
            throw "CLI invocation $Label returned an invalid UTF-8 JSON envelope; original output is retained."
        }
        $metadata.response_valid = $true; $metadata.ok = $document['ok']
        Write-CreoHelperJson $metadataPath $metadata
        if ($process.ExitCode -ne 0 -or $document['ok'] -ne $true) {
            $Run.Blocked = $true; $Run.BlockReason = 'cli_failure'
            throw "CLI invocation $Label failed; inspect its retained envelope and metadata. No automatic replay."
        }
        return $document
    } catch {
        if (-not $pending -and $metadata.state -ne 'finished') {
            $Run.Blocked = $true; $Run.BlockReason = 'invocation_failure'
            $metadata.state = 'invocation_failure'; $metadata.duration_seconds = $clock.Elapsed.TotalSeconds
            Write-CreoHelperJson $metadataPath $metadata
        }
        throw
    } finally {
        if (-not $pending) {
            if ($null -ne $stdoutStream) { $stdoutStream.Dispose() }
            if ($null -ne $stderrStream) { $stderrStream.Dispose() }
            if ($null -ne $process) { $process.Dispose() }
        }
    }
}

function Invoke-CreoCli {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Run,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string[]]$Arguments,
        [ValidateRange(0, 86400)][int]$TimeoutSeconds = 0
    )
    return Invoke-CreoCliCore $Run $Label $Arguments $TimeoutSeconds
}

function Invoke-CreoCliWrite {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Run,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string[]]$Arguments,
        [scriptblock]$Review,
        [ValidateRange(0, 86400)][int]$TimeoutSeconds = 0
    )
    if ($Arguments | Where-Object { $_ -match '^--(?:dry-run|confirm)(?:=|$)' }) { throw 'Write helper owns preview and confirmation flags; pass only unchanged business arguments.' }
    $preview = Invoke-CreoCli -Run $Run -Label ($Label + '-preview') -Arguments (@($Arguments) + '--dry-run') -TimeoutSeconds $TimeoutSeconds
    if ($preview.data.preview.can_apply -isnot [bool] -or $preview.data.preview.can_apply -ne $true -or
        $preview.data.confirm_token -isnot [string] -or [string]::IsNullOrWhiteSpace($preview.data.confirm_token)) {
        $Run.Blocked = $true; $Run.BlockReason = 'preview_not_applicable'
        throw 'Preview does not authorize applying this write; original preview is preserved and no confirmation was sent.'
    }
    if ($null -ne $Review) {
        try { $reviewed = @(& $Review $preview) }
        catch {
            $Run.Blocked = $true; $Run.BlockReason = 'preview_review_failed'
            throw
        }
        if ($reviewed.Count -ne 1 -or $reviewed[0] -isnot [bool] -or $reviewed[0] -ne $true) {
            $Run.Blocked = $true; $Run.BlockReason = 'preview_review_rejected'
            throw 'Preview review did not return exactly boolean true; no confirmation was sent.'
        }
    }
    $token = [string]$preview.data.confirm_token
    try {
        return Invoke-CreoCli -Run $Run -Label ($Label + '-confirm') -Arguments (@($Arguments) + @('--confirm', $token)) -TimeoutSeconds $TimeoutSeconds
    } finally { $token = $null }
}

function Get-CreoCliLocalOperation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Run,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$OperationId,
        [ValidateRange(0, 86400)][int]$TimeoutSeconds = 0
    )
    if ($OperationId -notmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$') { throw 'Use the exact retained operation identifier.' }
    return Invoke-CreoCliCore $Run $Label @('operation', 'show', '--id', $OperationId) $TimeoutSeconds -LocalOperationShow
}
