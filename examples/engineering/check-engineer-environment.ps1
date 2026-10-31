#requires -Version 7.4
<#
Packaged as START.ps1 at the delivery root. The default check is offline.
PackageRoot is an override for source tests; EnvironmentFile is always an explicit input.
Only public CLI discovery commands run. This script never creates an operation database.
#>
param(
    [string]$PackageRoot = $PSScriptRoot,
    [string]$EnvironmentFile,
    [switch]$Connect,
    [string]$CurrentDeliveryFile,
    [string]$ReportDirectory,
    [ValidateRange(1, 300)][int]$CommandTimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$calls = [System.Collections.Generic.List[object]]::new()
$childEnvironment = @{}
$reportPath = $null
$originalCliError = $null
$reportStorageFailures = [System.Collections.Generic.List[object]]::new()
$summary = [ordered]@{
    mode = $(if ($Connect) { 'process_only_connection' } else { 'offline' })
    package = @{ verified = $false }
    environment = @{ declared = [bool]$EnvironmentFile; dependencies_verified = $false }
    connection = @{ requested = [bool]$Connect; status = 'not_checked' }
    commands = $calls
    operation_database_created = $false
    CAD_calls = 0
    native_writes = 0
    limits = @(
        'Package hashes establish matching bytes, not publisher authenticity.'
        'Process-only component connection does not prove getter completion, CAD idle state or write availability.'
        'Preserve existing history and pending operations; a new CLI process does not recover a pending native call.'
    )
}

function Fail([string]$Code, [string]$Message, [string]$NextAction) {
    $failure = [System.Exception]::new($Message)
    $failure.Data['code'] = $Code
    $failure.Data['next_action'] = $NextAction
    throw $failure
}

function Absolute-Path([string]$Value, [string]$Label) {
    if (-not $Value -or -not [System.IO.Path]::IsPathFullyQualified($Value) -or
        $Value.StartsWith('\\') -or $Value.StartsWith('//') -or $Value -match '[\x00-\x1f]') {
        Fail 'E_CONFIG' "An absolute local path is required for $Label." 'Edit the explicit input to name an existing local dependency.'
    }
    $full = [System.IO.Path]::GetFullPath($Value)
    if ($full -eq [System.IO.Path]::GetPathRoot($full)) { return $full }
    return $full.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

function Inside([string]$Candidate, [string]$Root) {
    return $Candidate.Equals($Root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $Candidate.StartsWith($Root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Existing-Path([string]$Value, [string]$Label, [bool]$Directory = $false) {
    $resolved = Absolute-Path $Value $Label
    $exists = if ($Directory) { [System.IO.Directory]::Exists($resolved) } else { [System.IO.File]::Exists($resolved) }
    if (-not $exists) {
        Fail 'E_NOT_FOUND' "The declared $Label is missing." 'Correct the explicit declaration or have its owner provide the dependency; do not create or replace operation history.'
    }
    $cursor = $resolved
    while ($cursor) {
        if (([System.IO.File]::GetAttributes($cursor) -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            Fail 'E_CONFIG' "The declared $Label uses a symbolic link or junction." 'Use an existing local path without links or junctions.'
        }
        $cursor = [System.IO.Path]::GetDirectoryName($cursor)
    }
    return $resolved
}

function Read-Json([string]$Path, [string]$Label) {
    try {
        $value = [System.IO.File]::ReadAllText($Path, $utf8) | ConvertFrom-Json -AsHashtable -Depth 100
    } catch {
        Fail 'E_CONFIG' "The $Label is not a UTF-8 JSON object." 'Correct the named JSON input and run START.ps1 again.'
    }
    if ($value -isnot [System.Collections.IDictionary]) {
        Fail 'E_CONFIG' "The $Label must be a JSON object." 'Correct the named JSON input and run START.ps1 again.'
    }
    return $value
}

function Hash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Valid-Binding($Value) {
    return $Value -is [System.Collections.IDictionary] -and
        $Value.Contains('sha256') -and $Value.sha256 -is [string] -and
        $Value.sha256 -match '^[0-9a-fA-F]{64}$' -and $Value.Contains('bytes') -and
        ($Value.bytes -is [long] -or $Value.bytes -is [int]) -and $Value.bytes -ge 0
}

function Check-Database([string]$Path, [string]$Label) {
    $file = Existing-Path $Path $Label
    $stream = [System.IO.File]::Open($file, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $header = [byte[]]::new(16)
        if ($stream.Read($header, 0, 16) -ne 16 -or
            [System.Text.Encoding]::ASCII.GetString($header) -ne "SQLite format 3`0") {
            Fail 'E_CONFIG' "The declared $Label is not an existing SQLite database." 'Ask the history owner to identify the retained database; do not initialize an empty replacement.'
        }
    } finally { $stream.Dispose() }
    return $file
}

function Check-Pin($Pin) {
    if ($Pin -isnot [System.Collections.IDictionary] -or
        @('java_pid', 'native_pid', 'chain', 'process_creations', 'service_instance_id').Where({ -not $Pin.Contains($_) }).Count) {
        Fail 'E_CONFIG' 'Connect requires a complete structured runtime_pin declaration.' 'Obtain a time-stamped process identity declaration from the instance owner; a historical PID is insufficient.'
    }
    $instance = [guid]::Empty
    if (-not [guid]::TryParse([string]$Pin.service_instance_id, [ref]$instance) -or $instance -eq [guid]::Empty -or
        ($Pin.java_pid -isnot [long] -and $Pin.java_pid -isnot [int]) -or
        ($Pin.native_pid -isnot [long] -and $Pin.native_pid -isnot [int]) -or
        $Pin.java_pid -le 0 -or $Pin.native_pid -le 0 -or
        $Pin.chain -isnot [array] -or $Pin.chain.Count -lt 2 -or
        $Pin.chain[0] -ne $Pin.java_pid -or $Pin.chain[-1] -ne $Pin.native_pid -or
        $Pin.process_creations -isnot [System.Collections.IDictionary] -or
        $Pin.process_creations.Count -ne $Pin.chain.Count) {
        Fail 'E_CONFIG' 'The declared runtime_pin is incomplete or malformed.' 'Obtain the complete PID chain, exact process creation identities and service instance ID from the instance owner.'
    }
    $unique = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($processId in $Pin.chain) {
        if (($processId -isnot [long] -and $processId -isnot [int]) -or $processId -le 0 -or
            -not $unique.Add([string]$processId) -or -not $Pin.process_creations.Contains([string]$processId) -or
            [string]$Pin.process_creations[[string]$processId] -notmatch '^\d{15,20}$') {
            Fail 'E_CONFIG' 'The declared runtime_pin lacks exact process creation identities.' 'Obtain a current complete declaration; do not reuse opaque historical process IDs.'
        }
    }
}

function Check-Declaration($Declaration) {
    $issues = [System.Collections.Generic.List[object]]::new()
    $required = [System.Collections.Generic.List[string]]::new()
    foreach ($name in @('creo', 'java', 'installation', 'true_global_history')) {
        $required.Add($name)
        if (-not $Declaration.Contains($name)) { $issues.Add(@{ field = $name; problem = 'missing' }) }
        elseif ($Declaration[$name] -isnot [string] -or -not $Declaration[$name].Trim()) { $issues.Add(@{ field = $name; problem = 'nonempty_path_string_required' }) }
    }
    $required.Add('environment_variables')
    $variablesValid = $Declaration.Contains('environment_variables') -and $Declaration.environment_variables -is [System.Collections.IDictionary]
    if (-not $variablesValid) { $issues.Add(@{ field = 'environment_variables'; problem = 'object_required' }) }
    foreach ($name in $allowed) {
        $field = "environment_variables.$name"
        $required.Add($field)
        if (-not $variablesValid -or -not $Declaration.environment_variables.Contains($name)) { $issues.Add(@{ field = $field; problem = 'missing' }) }
        elseif ($Declaration.environment_variables[$name] -isnot [string] -or -not $Declaration.environment_variables[$name].Trim()) { $issues.Add(@{ field = $field; problem = 'nonempty_string_required' }) }
    }
    if ($Connect) {
        $required.Add('runtime_pin')
        foreach ($name in @('java_pid', 'native_pid', 'chain', 'process_creations', 'service_instance_id')) { $required.Add("runtime_pin.$name") }
        if (-not $Declaration.Contains('runtime_pin')) { $issues.Add(@{ field = 'runtime_pin'; problem = 'missing' }) }
        else {
            try { Check-Pin $Declaration.runtime_pin }
            catch { $issues.Add(@{ field = 'runtime_pin'; problem = 'complete_process_generation_required' }) }
        }
        $required.Add('observed_at_utc')
        $timestampValid = $false
        if ($Declaration.Contains('observed_at_utc')) {
            # JSON decoding may preserve a zoned timestamp as DateTime. Do not replace
            # missing provenance with this preflight's clock or the file's timestamp.
            $timestamp = $Declaration.observed_at_utc
            $observedAt = [DateTimeOffset]::MinValue
            if ($timestamp -is [DateTime]) { $timestampValid = $timestamp.Kind -ne [DateTimeKind]::Unspecified }
            elseif ($timestamp -is [string] -and $timestamp -match '(Z|[+-]\d\d:\d\d)$') { $timestampValid = [DateTimeOffset]::TryParse($timestamp, [ref]$observedAt) }
        }
        if (-not $timestampValid) { $issues.Add(@{ field = 'observed_at_utc'; problem = 'actual_zoned_observation_timestamp_required' }) }
        foreach ($name in @('creo-cli-service.jar', 'creo_cli_sketch.dll')) {
            $field = "component_files.$name"
            $required.Add($field)
            if (-not $Declaration.Contains('component_files') -or $Declaration.component_files -isnot [System.Collections.IDictionary] -or
                -not $Declaration.component_files.Contains($name) -or -not (Valid-Binding $Declaration.component_files[$name])) {
                $issues.Add(@{ field = $field; problem = 'sha256_and_bytes_binding_required' })
            }
        }
    }
    $summary.environment.declaration_required_fields = @($required.ToArray())
    $summary.environment.declaration_issues = @($issues.ToArray())
    if ($issues.Count) {
        Fail 'E_CONFIG' 'The environment declaration has missing or invalid required fields; all detected declaration issues are listed.' 'Complete every summary.environment.declaration_issues field from the supplied template and real owner-reviewed observations. Do not invent observed_at_utc, reuse a historical PID or treat process-only connection as CAD readiness.'
    }
}

function Check-ComponentFiles([string]$Installation, $Bindings) {
    $issues = [System.Collections.Generic.List[object]]::new()
    foreach ($name in @('creo-cli-service.jar', 'creo_cli_sketch.dll')) {
        try {
            $file = Existing-Path (Join-Path $Installation $name) 'installed component file'
            if ((Get-Item -LiteralPath $file).Length -ne $Bindings[$name].bytes -or (Hash $file) -ne $Bindings[$name].sha256) {
                $issues.Add(@{ file = $name; problem = 'declared_bytes_or_sha256_mismatch' })
            }
        } catch { $issues.Add(@{ file = $name; problem = 'missing_unreadable_or_linked_file' }) }
    }
    $summary.environment.component_file_issues = @($issues.ToArray())
    if ($issues.Count) {
        Fail 'E_CONFIG' 'The declared installed component files are missing, unreadable or differ from their byte bindings; all detected component issues are listed.' 'Have the instance owner verify every listed installed file and its real source. Do not edit a binding to bypass a mismatch or replace components in a running instance.'
    }
    $summary.environment.declared_component_files_verified = $true
}

function Same-Pin($Actual, $Expected) {
    Check-Pin $Actual
    if ($Actual.java_pid -ne $Expected.java_pid -or $Actual.native_pid -ne $Expected.native_pid -or
        [string]$Actual.service_instance_id -ne [string]$Expected.service_instance_id -or
        ($Actual.chain -join ',') -ne ($Expected.chain -join ',')) { return $false }
    foreach ($processId in $Expected.chain) {
        if ([string]$Actual.process_creations[[string]$processId] -ne [string]$Expected.process_creations[[string]$processId]) { return $false }
    }
    return $true
}

function Safe-Document($Value) {
    if ($Value -is [System.Collections.IDictionary]) {
        $secretKeys = @('password', 'secret', 'authorization', 'cookie', 'access_token', 'refresh_token', 'token', 'api_key', 'apikey', 'api-key', 'client_secret', 'private_key', 'sessionid', 'session_id', 'credential')
        $safe = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $sensitive = $key -in $secretKeys -or
                ($Value.Contains('name') -and [string]$Value.name -in $secretKeys -and $key -eq 'value') -or
                ($Value.Contains('target') -and [string]$Value.target -in $secretKeys -and $key -in @('before', 'after'))
            $safe[$key] = if ($sensitive) { '<redacted>' } else { Safe-Document $Value[$key] }
        }
        return $safe
    }
    if ($Value -is [array]) { return ,@($Value | ForEach-Object { Safe-Document $_ }) }
    return $Value
}

function Write-New([string]$Path, [string]$Text) {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try { $bytes = $utf8.GetBytes($Text); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

function Note-ReportFailure([string]$Phase) {
    $reportStorageFailures.Add(@{ phase = $Phase; partial_files_may_exist = $true })
}

function Storage-Error {
    return @{
        code = 'E_IO'
        retryable = $false
        failures = @($reportStorageFailures.ToArray())
        next_action = 'Choose a new writable external ReportDirectory; existing evidence is preserved.'
    }
}

function Save-CallRecord([string]$Label, $Output, $Exit) {
    if (-not $reportPath) { return }
    try {
        $stem = '{0:D2}-{1}' -f $calls.Count, $Label
        Write-New (Join-Path $reportPath ($stem + '.stdout.json')) (($Output | ConvertTo-Json -Depth 100) + "`n")
        Write-New (Join-Path $reportPath ($stem + '.exit.json')) (($Exit | ConvertTo-Json -Compress) + "`n")
    } catch {
        # Reporting is secondary to the already captured public CLI outcome.
        # Never echo the filesystem exception, which can contain external text.
        Note-ReportFailure 'command_records'
    }
}

function Invoke-Public([string[]]$Arguments, [string]$Label) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $script:exe
    $start.WorkingDirectory = $script:packagePath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $utf8
    $start.StandardErrorEncoding = $utf8
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    foreach ($key in @($start.Environment.Keys)) {
        if ($key -like 'CREO_CLI_*') { [void]$start.Environment.Remove($key) }
    }
    foreach ($key in $childEnvironment.Keys) { $start.Environment[$key] = $childEnvironment[$key] }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    $timedOut = $false
    $deadline = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $remaining = [int][Math]::Max(0, $CommandTimeoutSeconds * 1000 - $deadline.ElapsedMilliseconds)
        if (-not $process.WaitForExit($remaining)) {
            $timedOut = $true
        } else {
            $remaining = [int][Math]::Max(0, $CommandTimeoutSeconds * 1000 - $deadline.ElapsedMilliseconds)
            # Descendants can inherit a pipe after the direct EXE exits. The same
            # deadline covers stream completion, without killing any process.
            if (-not [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask), $remaining)) {
                $timedOut = $true
            } else {
                $stdout = $stdoutTask.GetAwaiter().GetResult()
                [void]$stderrTask.GetAwaiter().GetResult()
                $exitCode = $process.ExitCode
            }
        }
    } catch {
        Fail 'E_IO' 'The packaged public EXE could not run.' 'Use a supported Windows host and confirm the verified EXE can execute; preserve the package.'
    } finally { $process.Dispose() }
    if ($timedOut) {
        $calls.Add(@{ command = $Label; exit_code = $null; ok = $false; timed_out = $true })
        Save-CallRecord $Label @{ output_retained = $false; reason = 'CLI deadline elapsed; no process cancellation was attempted.' } @{ exit_code = $null; timed_out = $true }
        Fail 'E_VERIFY_INCOMPLETE' "Public discovery command $Label did not finish within its deadline; its process may still be running." 'Preserve observations and inspect the CLI process independently; preflight did not kill it or cancel any pending work.'
    }
    try { $document = $stdout | ConvertFrom-Json -AsHashtable -Depth 100 } catch { $document = $null }
    $valid = $document -is [System.Collections.IDictionary] -and $document.Contains('ok') -and
        $document.ok -is [bool] -and $document.Contains('schema_version')
    $succeeded = $exitCode -eq 0 -and $valid -and $document.ok -eq $true -and
        $document.Contains('data') -and $document.data -is [System.Collections.IDictionary]
    $call = @{ command = $Label; exit_code = $exitCode; ok = [bool]$succeeded }
    if ($valid -and $document.ok -eq $false -and $document.Contains('error') -and
        $document.error -is [System.Collections.IDictionary] -and
        $document.error.Contains('code') -and $document.error.code -is [string] -and
        $document.error.code -cmatch '^E_[A-Z][A-Z0-9_]{0,63}$' -and
        $document.error.Contains('retryable') -and $document.error.retryable -is [bool]) {
        # Retain the original machine classification before any report write.
        # Unknown message/details and purported correlation/evidence IDs are omitted.
        $script:originalCliError = @{
            code = $document.error.code
            retryable = $document.error.retryable
            exit_code = $exitCode
        }
        $call['original_cli_error'] = $originalCliError
    }
    $calls.Add($call)
    $saved = if ($succeeded) { Safe-Document $document } else { @{ output_retained = $false; reason = 'Failure text is not echoed or retained.' } }
    if ($originalCliError) { $saved['original_cli_error'] = $originalCliError }
    Save-CallRecord $Label $saved @{ exit_code = $exitCode }
    if (-not $succeeded) {
        Fail 'E_CONFIG' "Public discovery command $Label did not succeed." 'Inspect the exit record and verified CLI documentation; correct dependencies without replacing retained history.'
    }
    if ($reportStorageFailures.Count) {
        Fail 'E_IO' 'The public CLI completed, but its report records could not be retained.' 'Choose a new writable external ReportDirectory; existing evidence is preserved.'
    }
    return $document.data
}

$exitStatus = 0
try {
    $packagePath = Existing-Path (Absolute-Path $PackageRoot 'package root') 'package root' $true
    if ($ReportDirectory) {
        $reportPath = Absolute-Path $ReportDirectory 'report directory'
        if ((Inside $reportPath $packagePath) -or (Test-Path -LiteralPath $reportPath)) {
            $reportPath = $null
            Fail 'E_CONFIG' 'ReportDirectory must be a new directory outside the package.' 'Choose a new external evidence directory; existing evidence is never overwritten.'
        }
        [void](Existing-Path ([System.IO.Path]::GetDirectoryName($reportPath)) 'report parent directory' $true)
        [void][System.IO.Directory]::CreateDirectory($reportPath)
    }
    if ($EnvironmentFile) {
        $declaration = Read-Json (Existing-Path (Absolute-Path $EnvironmentFile 'environment file') 'environment file') 'environment declaration'
        $allowed = @('CREO_CLI_WORKSPACE', 'CREO_CLI_CONFIG_DIR', 'CREO_CLI_PERMISSION', 'CREO_CLI_EXPERIMENTAL_NATIVE_WRITES', 'CREO_CLI_SERVICE_URL', 'CREO_CLI_SERVICE_TOKEN_FILE', 'CREO_CLI_SCOPE_FILE')
        Check-Declaration $declaration
        foreach ($key in $declaration.environment_variables.Keys) {
            if ($key -notin $allowed -or $declaration.environment_variables[$key] -isnot [string]) { Fail 'E_CONFIG' 'The declaration contains an unsupported environment variable or value.' 'Keep only documented CREO_CLI variables; place credentials in the declared token file.' }
            $childEnvironment[$key] = $declaration.environment_variables[$key]
        }
        foreach ($key in $allowed) {
            if (-not $childEnvironment.ContainsKey($key)) { Fail 'E_CONFIG' "The environment declaration lacks $key." 'Declare every documented environment variable explicitly; do not infer credentials or history paths.' }
        }
        if ($childEnvironment.CREO_CLI_PERMISSION -notin @('read', 'write') -or $childEnvironment.CREO_CLI_EXPERIMENTAL_NATIVE_WRITES -notin @('0', '1')) { Fail 'E_CONFIG' 'The declared policy values are invalid.' 'Use read/write and 0/1 as documented; preflight itself never authorizes CAD writes.' }
        $endpoint = $null
        if (-not [uri]::TryCreate($childEnvironment.CREO_CLI_SERVICE_URL, [System.UriKind]::Absolute, [ref]$endpoint) -or
            $endpoint.Scheme -ne 'http' -or $endpoint.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1') -or
            $endpoint.UserInfo -or $endpoint.AbsolutePath -ne '/' -or $endpoint.Query -or $endpoint.Fragment) { Fail 'E_CONFIG' 'The declared service URL must be loopback HTTP without credentials or a path.' 'Declare the existing owned instance loopback endpoint in the environment JSON.' }
        $creoPath = Existing-Path $declaration.creo 'Creo root' $true
        $javaPath = Existing-Path $declaration.java 'JDK root' $true
        $installationPath = Existing-Path $declaration.installation 'installation directory' $true
        foreach ($file in @((Join-Path $creoPath 'Common Files/x86e_win64/obj/xtop.exe'), (Join-Path $creoPath 'Parametric/bin/parametric.exe'), (Join-Path $javaPath 'bin/java.exe'))) { [void](Existing-Path $file 'declared host executable') }
        foreach ($name in @('manifest.json', 'protk.dat')) { [void](Existing-Path (Join-Path $installationPath $name) 'installed component file') }
        if ($Connect) { Check-ComponentFiles $installationPath $declaration.component_files }
        else {
            foreach ($name in @('creo-cli-service.jar', 'creo_cli_sketch.dll')) { [void](Existing-Path (Join-Path $installationPath $name) 'installed component file') }
        }
        [void](Existing-Path $childEnvironment.CREO_CLI_WORKSPACE 'workspace directory' $true)
        $configPath = Existing-Path $childEnvironment.CREO_CLI_CONFIG_DIR 'continuous history directory' $true
        [void](Check-Database (Join-Path $configPath 'operations.sqlite3') 'continuous operation history')
        [void](Check-Database $declaration.true_global_history 'true global operation history')
        [void](Existing-Path $childEnvironment.CREO_CLI_SCOPE_FILE 'scope file')
        $tokenPath = Existing-Path $childEnvironment.CREO_CLI_SERVICE_TOKEN_FILE 'token file'
        if (Inside $tokenPath $packagePath) { Fail 'E_CONFIG' 'The credential file must be outside the package payload.' 'Keep the existing token file external and declare only its path; never include token bytes in a delivery.' }
        $summary.environment.dependencies_verified = $true
        $summary.environment.history_preserved = $true
        $summary.environment.token_contents_read_by_preflight = $false
    } elseif ($Connect) { Fail 'E_CONFIG' 'Connect requires an explicit EnvironmentFile.' 'Run START.ps1 -EnvironmentFile <engineer-owned.json> -Connect after completing the declaration.' }

    $manifestPath = Existing-Path (Join-Path $packagePath 'PACKAGE-MANIFEST.json') 'package manifest'
    $manifest = Read-Json $manifestPath 'package manifest'
    if (-not $manifest.Contains('files') -or $manifest.files -isnot [System.Collections.IDictionary] -or -not $manifest.files.Count) { Fail 'E_INTEGRITY' 'The package manifest lacks a complete files map.' 'Obtain a complete delivery with its root PACKAGE-MANIFEST.json.' }
    $expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $manifest.files.Keys) {
        if ($name -isnot [string] -or $name -match '[\\:\x00-\x1f]' -or $name.StartsWith('/') -or
            @($name.Split('/')).Where({ $_ -in @('', '.', '..') }).Count -or
            $name -ieq 'PACKAGE-MANIFEST.json' -or -not $expected.Add($name) -or -not (Valid-Binding $manifest.files[$name])) { Fail 'E_INTEGRITY' 'The package manifest has an unsafe, duplicate or invalid payload entry.' 'Obtain an intact package; do not edit its manifest to bypass verification.' }
    }
    $actual = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($item in Get-ChildItem -LiteralPath $packagePath -Recurse -Force) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { Fail 'E_INTEGRITY' 'Package payload contains a symbolic link or junction.' 'Extract an intact delivery into a new local directory without links.' }
        if (-not $item.PSIsContainer) {
            $relative = [System.IO.Path]::GetRelativePath($packagePath, $item.FullName).Replace('\', '/')
            if ($relative -ieq 'PACKAGE-MANIFEST.json') { continue }
            [void]$actual.Add($relative)
        }
    }
    if (-not $actual.SetEquals($expected)) { Fail 'E_INTEGRITY' 'Package payload has missing or extra files.' 'Extract the original archive into a new empty directory and rerun START.ps1.' }
    foreach ($name in $manifest.files.Keys) {
        $file = Join-Path $packagePath $name
        if ((Get-Item -LiteralPath $file).Length -ne $manifest.files[$name].bytes -or (Hash $file) -ne $manifest.files[$name].sha256) { Fail 'E_INTEGRITY' 'Package payload hash or size differs from its manifest.' 'Preserve the damaged copy and extract a fresh delivery; never repair the manifest around changed bytes.' }
    }
    if ($manifest.Contains('file_count_excluding_manifest') -and $manifest.file_count_excluding_manifest -ne $expected.Count) { Fail 'E_INTEGRITY' 'The manifest file count differs from its files map.' 'Obtain a complete consistent delivery.' }
    $exe = Existing-Path (Join-Path $packagePath 'cli/creo-cli.exe') 'public CLI executable'
    if (-not $expected.Contains('cli/creo-cli.exe')) { Fail 'E_INTEGRITY' 'The public CLI executable is not bound by the manifest.' 'Obtain a delivery whose manifest binds cli/creo-cli.exe.' }
    $summary.package = @{ verified = $true; payload_files = $expected.Count; manifest_sha256 = Hash $manifestPath; client_exe_sha256 = Hash $exe }
    if ($CurrentDeliveryFile) {
        $current = Read-Json (Existing-Path (Absolute-Path $CurrentDeliveryFile 'current delivery file') 'current delivery file') 'selected current delivery'
        if (-not $current.Contains('package') -or $current.package -isnot [System.Collections.IDictionary]) { Fail 'E_CONFIG' 'The selected delivery file lacks package bindings.' 'Select the delivery JSON that explicitly binds this package manifest and public EXE.' }
        foreach ($name in @('manifest', 'client_exe')) {
            if (-not $current.package.Contains($name) -or -not (Valid-Binding $current.package[$name]) -or -not $current.package[$name].Contains('path')) { Fail 'E_CONFIG' 'The selected delivery file has an incomplete package binding.' 'Select the delivery JSON with manifest/client_exe path, sha256 and bytes bindings.' }
            $binding = $current.package[$name]
            $selected = Existing-Path $binding.path 'selected delivery artifact'
            $local = if ($name -eq 'manifest') { $manifestPath } else { $exe }
            if ((Hash $selected) -ne $binding.sha256 -or (Get-Item -LiteralPath $selected).Length -ne $binding.bytes -or (Hash $local) -ne $binding.sha256 -or (Get-Item -LiteralPath $local).Length -ne $binding.bytes) { Fail 'E_INTEGRITY' 'The selected delivery manifest or EXE differs from this package.' 'Use the intended intact package and matching explicit delivery binding.' }
        }
        $summary.package.explicit_current_delivery_matches = $true
    }
    $version = Invoke-Public @('--version') 'version'
    $index = Invoke-Public @('reference', '--index', '--compact') 'reference-index'
    $context = Invoke-Public @('context', '--compact') 'context-offline'
    if (-not $version.Contains('version') -or -not $index.Contains('commands') -or -not $index.Contains('version') -or
        -not $context.Contains('version') -or $version.version -ne $index.version -or $version.version -ne $context.version) { Fail 'E_INTEGRITY' 'Public CLI discovery responses are incomplete or disagree on version.' 'Preserve the outputs and obtain a consistent delivery.' }
    $summary.package.version = $version.version
    $summary.package.registered_commands = $index.commands.Count
    if ($EnvironmentFile -and (-not $context.Contains('state') -or $context.state -isnot [System.Collections.IDictionary] -or -not $context.state.Contains('available') -or $context.state.available -isnot [bool] -or $context.state.available -ne $true)) { Fail 'E_CONFIG' 'The declared retained operation state is not readable by offline context.' 'Inspect the retained history and permissions with its owner; do not create an empty replacement.' }
    if ($Connect) {
        $connected = Invoke-Public @('context', '--installation', $installationPath, '--creo', $creoPath, '--java-home', $javaPath, '--compact') 'context-process-only'
        if (-not $connected.Contains('extensions') -or $connected.extensions -isnot [System.Collections.IDictionary] -or
            -not $connected.extensions.Contains('creo') -or $connected.extensions.creo -isnot [System.Collections.IDictionary] -or
            -not $connected.extensions.creo.Contains('installation')) { Fail 'E_VERIFY_INCOMPLETE' 'The process-only context lacks an installation identity observation.' 'Preserve the context output and obtain complete public installation identity evidence; health alone is insufficient.' }
        $installation = $connected.extensions.creo.installation
        if ($installation -isnot [System.Collections.IDictionary] -or -not $installation.Contains('files_verified') -or
            -not $installation.Contains('loaded_verified') -or $installation.files_verified -isnot [bool] -or $installation.loaded_verified -isnot [bool] -or $installation.files_verified -ne $true -or $installation.loaded_verified -ne $true -or
            -not $installation.Contains('runtime_identity') -or $installation.runtime_identity -isnot [System.Collections.IDictionary] -or -not $installation.runtime_identity.Contains('passed') -or $installation.runtime_identity.passed -isnot [bool] -or $installation.runtime_identity.passed -ne $true -or
            -not $installation.Contains('runtime_pin')) { Fail 'E_VERIFY_INCOMPLETE' 'Current process-only component identity is not fully verified.' 'Preserve the context observation and have the instance owner resolve file/load identity; health alone is insufficient.' }
        if (-not (Same-Pin $installation.runtime_pin $declaration.runtime_pin)) { Fail 'E_CONFLICT' 'The observed runtime generation differs from the explicit declaration.' 'Obtain a new owner-reviewed declaration for the actual generation; do not connect using a historical PID.' }
        if (-not $installation.Contains('installation') -or
            -not ([System.IO.Path]::GetFullPath([string]$installation.installation)).Equals($installationPath, [System.StringComparison]::OrdinalIgnoreCase)) { Fail 'E_VERIFY_FAILED' 'The observed installation differs from the explicit declared target.' 'Preserve the process-only context and ask the instance owner to identify the selected installation.' }
        if (-not $connected.Contains('environment') -or $connected.environment -isnot [System.Collections.IDictionary] -or
            -not $connected.environment.Contains('connection') -or $connected.environment.connection -isnot [System.Collections.IDictionary]) { Fail 'E_VERIFY_INCOMPLETE' 'Public context lacks a current projected connection status.' 'Preserve the context observation and resolve missing process/component evidence with the instance owner.' }
        $connection = $connected.environment.connection
        if (-not $connection.Contains('status') -or $connection.status -ne 'connected' -or
            -not $connection.Contains('instance_id') -or $connection.instance_id -ne $declaration.runtime_pin.service_instance_id -or
            -not $connection.Contains('generation') -or $connection.generation -isnot [string] -or -not $connection.generation) { Fail 'E_VERIFY_INCOMPLETE' 'Public context does not project the declared current generation as connected.' 'Preserve the context observation and resolve its unavailable or inconsistent identity; do not promote health alone.' }
        foreach ($name in @('creo-cli-service.jar', 'creo_cli_sketch.dll')) {
            if (-not $installation.Contains('component_files') -or -not $installation.component_files.Contains($name) -or
                -not (Valid-Binding $installation.component_files[$name]) -or
                $installation.component_files[$name].sha256 -ne $declaration.component_files[$name].sha256 -or
                $installation.component_files[$name].bytes -ne $declaration.component_files[$name].bytes) { Fail 'E_VERIFY_FAILED' 'Observed component bytes differ from the explicit declaration.' 'Preserve both observations and ask the instance owner to identify the selected installed components.' }
        }
        $summary.connection = @{ requested = $true; status = 'verified_process_only'; files_verified = $true; loaded_verified = $true; runtime_pin_matches = $true; CAD_readiness = 'not_assessed' }
    }
    $document = @{ ok = $true; schema_version = '1.0'; data = $summary }
} catch {
    $known = $_.Exception.Data.Contains('code')
    if ($originalCliError) {
        $errorCode = $originalCliError.code
        $exitStatus = if ($originalCliError.exit_code -ne 0) { $originalCliError.exit_code } else { 1 }
        $retryable = $originalCliError.retryable
        $message = 'Public CLI discovery failed; its original machine classification and actual exit are retained.'
        $nextAction = 'Preserve the original classification and retained diagnostics; inspect them with the instance owner. This helper does not retry, cancel or recover native work.'
    } else {
        $errorCode = if ($known) { $_.Exception.Data['code'] } else { 'E_CONFIG' }
        $exitStatus = switch ($errorCode) { 'E_CONFIG' { 4 } 'E_NOT_FOUND' { 3 } 'E_CONFLICT' { 6 } default { 1 } }
        $retryable = $false
        $message = if ($known) { $_.Exception.Message } else { 'Preflight could not verify the declared package or environment.' }
        $nextAction = if ($known) { $_.Exception.Data['next_action'] } else { 'Check the documented input structure and existing local dependencies; preserve history and rerun START.ps1.' }
    }
    $document = @{ ok = $false; schema_version = '1.0'; error = @{
        code = $errorCode
        message = $message
        retryable = $retryable
        details = @{ next_action = $nextAction; summary = $summary }
    } }
    if ($originalCliError) { $document.error.details['original_cli_error'] = $originalCliError }
}
if ($reportStorageFailures.Count) { $document.error.details['report_storage_error'] = Storage-Error }
$json = ($document | ConvertTo-Json -Depth 100 -Compress) + "`n"
if ($reportPath) {
    try {
        Write-New (Join-Path $reportPath 'REPORT.stdout.json') $json
        Write-New (Join-Path $reportPath 'REPORT.exit.json') ((@{ exit_code = $exitStatus } | ConvertTo-Json -Compress) + "`n")
    } catch {
        Note-ReportFailure 'final_report'
        if ($document.ok -eq $true) {
            $exitStatus = 1
            $document = @{ ok = $false; schema_version = '1.0'; error = @{
                code = 'E_IO'
                message = 'The public CLI completed, but the final report could not be retained.'
                retryable = $false
                details = @{ next_action = 'Choose a new writable external ReportDirectory; existing evidence is preserved.'; summary = $summary }
            } }
        }
        $document.error.details['report_storage_error'] = Storage-Error
        $json = ($document | ConvertTo-Json -Depth 100 -Compress) + "`n"
    }
}
[Console]::Out.Write($json)
exit $exitStatus
