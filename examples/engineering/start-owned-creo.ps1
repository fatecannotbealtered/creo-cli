#requires -Version 7.4
<#
Start one explicitly owned test instance using an installed component directory.
Both registered components auto-start. This recipe never edits global configuration,
accepts trust/license prompts, sends desktop input, or stops any process.
Keep the CLI's existing history directory; the child runtime directory is separate.
#>
param(
    [Parameter(Mandatory)][string]$CreoRoot,
    [Parameter(Mandatory)][string]$JavaHome,
    [Parameter(Mandatory)][string]$InstallationDirectory,
    [Parameter(Mandatory)][string]$StartupDirectory,
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [ValidateRange(1024, 65535)][int]$Port = 9202,
    [ValidateRange(5, 900)][int]$WaitSeconds = 180,
    [ValidateRange(5, 60)][int]$SessionTimeoutSeconds = 30,
    [switch]$JavaOnlyDiagnostic,
    [string]$InitialModel,
    [ValidateSet('inherit', 'signed-only', 'internal-unsigned-trial')][string]$TrustPolicy = 'inherit',
    [string]$ExpectedNativeSignerThumbprint,
    [string]$InternalTrialBinding,
    [string]$ExpectedInternalTrialBindingSha256,
    [string]$LoginConfigurationDirectory,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
$requireNative = -not $JavaOnlyDiagnostic
$loginConfigurationExplicit = $PSBoundParameters.ContainsKey('LoginConfigurationDirectory')

function Resolve-OwnedPath([string]$Value) {
    if (-not [System.IO.Path]::IsPathFullyQualified($Value) -or
        $Value.StartsWith('\\') -or $Value.Contains('"') -or @($Value.ToCharArray() | Where-Object { [char]::IsControl($_) }).Count) {
        throw 'Use an absolute local path without quotes or control characters.'
    }
    return [System.IO.Path]::GetFullPath($Value)
}

$launchCreoRoot = Resolve-OwnedPath $CreoRoot
$launchJavaRoot = Resolve-OwnedPath $JavaHome
$installedPath = Resolve-OwnedPath $InstallationDirectory
$startupPath = Resolve-OwnedPath $StartupDirectory
$runtimePath = Resolve-OwnedPath $RuntimeDirectory
$workflowRootPath = Join-Path $runtimePath 'wfroot'
$lastSessionPath = Join-Path $runtimePath 'session-history'
$creoExecutable = Join-Path $launchCreoRoot 'Parametric/bin/parametric.exe'
$creoPsf = Join-Path $launchCreoRoot 'Parametric/bin/parametric.psf'
$javaExecutable = Join-Path $launchJavaRoot 'bin/java.exe'
$manifestPath = Join-Path $installedPath 'manifest.json'
$registryPath = Join-Path $installedPath 'protk.dat'
$processHostScript = Join-Path $PSScriptRoot 'Start-OwnedCreoProcess.ps1'
$recoveryHelperPath = Join-Path $PSScriptRoot 'RecoveryIsolation.ps1'
foreach ($requiredFile in @($creoExecutable, $creoPsf, $javaExecutable, $manifestPath, $registryPath, $processHostScript, $recoveryHelperPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required declared dependency is missing: $requiredFile"
    }
}
. $recoveryHelperPath
$initialModelRecord = $null
$launchArguments = @($creoPsf)
$declaredPsfArgument = $creoPsf
if ($PSBoundParameters.ContainsKey('InitialModel')) {
    $modelPath = Resolve-OwnedPath $InitialModel
    if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf) -or
        [System.IO.Path]::GetFileName($modelPath) -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,30}\.(prt|asm)\.[1-9][0-9]*$') {
        throw 'InitialModel must be one existing exact numbered .prt or .asm file with a supported native model name.'
    }
    $modelFile = Get-Item -LiteralPath $modelPath -Force
    if (($modelFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'InitialModel cannot be a link or reparse point.' }
    $initialModelRecord = [ordered]@{
        path = $modelPath; sha256 = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = $modelFile.Length; last_write_utc = $modelFile.LastWriteTimeUtc.ToString('o')
        selection = 'exact_file_argument'; input_bytes_unchanged_after_start = $false
        context_qualification = 'Single-model startup only; CurrentModel/window and exact native state require independent public CLI readback.'
    }
    # PTC's installed file association uses parametric.exe "%1". The proven
    # diagnostic is file-only; do not claim a PSF+file combination was qualified.
    $launchArguments = @($modelPath)
    $declaredPsfArgument = $null
}
if ((Test-Path -LiteralPath $startupPath) -or (Test-Path -LiteralPath $runtimePath)) {
    throw 'Startup and runtime directories must be new; existing contents are preserved.'
}
$bundleManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($bundleManifest.tool -ne 'creo-cli' -or $bundleManifest.protocol -ne 2 -or
    $bundleManifest.java_app_class -notmatch '^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$') {
    throw 'The declared component manifest or Java entry class is invalid.'
}
if ($bundleManifest.runtime_profile.mode -ne 'environment') {
    throw 'This recipe requires an environment-based portable component profile.'
}
if ($null -eq $bundleManifest.files.'creo-cli-service.jar' -or
    $null -eq $bundleManifest.files.'creo_cli_sketch.dll' -or
    $bundleManifest.component_source_sha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'This startup recipe requires both declared components and their source fingerprint.'
}
foreach ($payload in $bundleManifest.files.PSObject.Properties) {
    if ($payload.Name -notin @('creo-cli-service.jar', 'creo_cli_sketch.dll')) {
        throw 'Unexpected component filename; installation must be inspected first.'
    }
    $payloadPath = Join-Path $installedPath $payload.Name
    $payloadHash = (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($payloadHash -ne $payload.Value.sha256) { throw "Installed bytes changed: $payloadPath" }
}

# A file/unlock stamp cannot authorize a publisher or avoid a source prompt. This
# preflight is file-only and finishes before any process/runtime creation.
$preflightRecord = [ordered]@{
    status = 'not_started'; stage = 'deployment_preflight'; process_started = $false
    recorded_at_utc = [DateTime]::UtcNow.ToString('o'); require_native = $requireNative
    trust_policy_requested = $TrustPolicy; startup = $startupPath; runtime = $runtimePath
    manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    expected_native_signer_thumbprint = $ExpectedNativeSignerThumbprint
    native_signature = $null; configuration_sources = @(); inherited_policy = $null
    internal_trial = $null; internal_isolation = $null
    proposed_policy = $null; local_configuration_written = $false
    session_readiness_attempts = 0; desktop_input_count = 0; cua_input_count = 0
    qualification = 'file_only_preflight_not_component_load_or_engineering_acceptance'
    failure = $null; next_action = $null
}
$preflightPath = $startupPath + '.preflight-' + [guid]::NewGuid().ToString('N') + '.json'
$preflightRecord.report_path = $preflightPath
$preflightCode = 'deployment_preflight_incomplete'

function Save-DeploymentPreflight {
    $text = $preflightRecord | ConvertTo-Json -Depth 16
    $stream = [System.IO.FileStream]::new($preflightPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        $encoded = [System.Text.UTF8Encoding]::new($false).GetBytes($text + "`n")
        $stream.Write($encoded, 0, $encoded.Length)
    } finally { $stream.Dispose() }
}
function Read-DeclaredPolicy {
    $loginRoot = if ($loginConfigurationExplicit) {
        Resolve-OwnedPath $LoginConfigurationDirectory
    } elseif (-not [string]::IsNullOrEmpty($LoginConfigurationDirectory)) {
        Resolve-OwnedPath $LoginConfigurationDirectory
    } else { [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile) }
    $roots = @(
        @{ kind = 'installation'; path = (Join-Path $launchCreoRoot 'Common Files/text') },
        @{ kind = 'login'; path = $loginRoot }
    )
    if ($TrustPolicy -eq 'internal-unsigned-trial') {
        foreach ($root in @(Get-InternalSourceRoots)) { $roots += @{ kind = 'audited_internal_source'; path = $root } }
    }
    if (-not [string]::IsNullOrEmpty($env:PTC_CREO_ALT_SETTINGS_PATH)) {
        $roots += @{ kind = 'declared_alternate'; path = (Resolve-OwnedPath $env:PTC_CREO_ALT_SETTINGS_PATH) }
    }
    $values = @{ open_protk_signed_apps = $null; open_protk_unsigned_apps = 'prompt' }
    $locked = @{}
    foreach ($root in $roots) {
        foreach ($filename in @('config.sup', 'config.pro')) {
            $filePath = Join-Path $root.path $filename
            $source = [ordered]@{ path = $filePath; kind = $root.kind; protected = ($filename -eq 'config.sup'); exists = (Test-Path -LiteralPath $filePath); selected_values = @{} }
            $preflightRecord.configuration_sources += $source
            if (-not $source.exists) { continue }
            $item = Get-Item -LiteralPath $filePath -Force -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Declared configuration is a link or not a regular file; no launch.' }
            $hashBefore = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
            foreach ($line in [System.IO.File]::ReadAllLines($filePath)) {
                if ($line -notmatch '^\s*(open_protk_signed_apps|open_protk_unsigned_apps)(?:\s|$)') { continue }
                if ($line -notmatch '^\s*(open_protk_signed_apps|open_protk_unsigned_apps)\s+(always|never|prompt)\s*(?:[!#].*)?$') {
                    throw 'A selected Toolkit loading option is malformed or unknown; no launch.'
                }
                $key = $Matches[1].ToLowerInvariant(); $value = $Matches[2].ToLowerInvariant()
                $source.selected_values[$key] = $value
            }
            $source.sha256 = $hashBefore
            if ((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashBefore) { throw 'Declared configuration changed during preflight; no launch.' }
            foreach ($key in $source.selected_values.Keys) {
                $value = $source.selected_values[$key]
                if ($source.protected) {
                    if ($locked.ContainsKey($key) -and $locked[$key] -ne $value) { throw 'Protected configuration values conflict; no launch.' }
                    $locked[$key] = $value
                    $values[$key] = $value
                } elseif (-not $locked.ContainsKey($key)) { $values[$key] = $value }
            }
        }
    }
    return @{ values = $values; locked = $locked; login_directory = $loginRoot }
}
function Require-EffectiveDeploymentPolicy([object]$Response, [string]$Requested, [string]$ExpectedUnsigned, [string]$PolicyProfile = 'all-options') {
    if ($null -eq $Response -or $null -eq $Response.PSObject.Properties['deployment_policy']) {
        throw 'Actual effective Toolkit policy readback is absent; full startup is not qualified.'
    }
    $actual = $Response.deployment_policy
    foreach ($key in @('complete', 'signed_apps', 'unsigned_apps')) {
        if ($null -eq $actual -or $null -eq $actual.PSObject.Properties[$key]) {
            throw 'Actual effective Toolkit policy readback is incomplete; full startup is not qualified.'
        }
    }
    if ($PolicyProfile -eq 'creo-13.4.1.0-unsigned-native') {
        if ($Requested -ne 'internal-unsigned-trial' -or $actual.complete -isnot [bool] -or $actual.complete -ne $false -or
            $null -ne $actual.signed_apps -or $actual.unsigned_apps -isnot [string] -or [string]$actual.unsigned_apps -notmatch '^(?i:always)$') {
            throw 'The bounded unsigned-native profile has conflicting or incomplete actual policy observations.'
        }
        $signed = $actual.signed_observation; $unsigned = $actual.unsigned_observation
        foreach ($observation in @($signed, $unsigned)) {
            foreach ($key in @('option', 'status', 'raw', 'raw_truncated', 'exception_category', 'exception_class')) {
                if ($null -eq $observation -or $null -eq $observation.PSObject.Properties[$key]) { throw 'Typed native policy observation is absent or incomplete.' }
            }
            if ($observation.raw_truncated -isnot [bool] -or $observation.raw_truncated -ne $false) { throw 'Truncated or untyped native policy observations are not accepted.' }
        }
        if ($signed.option -ne 'open_protk_signed_apps' -or $unsigned.option -ne 'open_protk_unsigned_apps' -or
            $unsigned.status -ne 'recognized' -or $unsigned.raw -isnot [string] -or
            [string]$unsigned.raw -notmatch '^\s*(?i:always)\s*$' -or
            $null -ne $unsigned.exception_category -or $null -ne $unsigned.exception_class) {
            throw 'The applicable unsigned option is not a complete successful Always readback.'
        }
        $unsupported = (
            ($signed.status -eq 'unsupported_null' -and $null -eq $signed.raw -and $null -eq $signed.exception_category -and $null -eq $signed.exception_class) -or
            ($signed.status -eq 'unsupported_empty' -and $signed.raw -is [string] -and $signed.raw.Length -eq 0 -and $null -eq $signed.exception_category -and $null -eq $signed.exception_class) -or
            ($signed.status -eq 'unsupported_not_found' -and $null -eq $signed.raw -and $signed.exception_category -eq 'XToolkitNotFound' -and $signed.exception_class -is [string] -and -not [string]::IsNullOrEmpty($signed.exception_class))
        )
        if (-not $unsupported) { throw 'A nonempty, unrecognized or failed signed-option observation is not a supported unavailable option.' }
        $qualified = [ordered]@{}
        foreach ($property in $actual.PSObject.Properties) { $qualified[$property.Name] = $property.Value }
        $qualified.policy_profile = $PolicyProfile
        $qualified.applicable_policy_verified = $true
        $qualified.signed_apps_verified = $false
        $qualified.full_policy_option_set_verified = $false
        return $qualified
    }
    if (-not [string]::IsNullOrEmpty($PolicyProfile) -and $PolicyProfile -ne 'all-options') { throw 'Unknown actual policy profile; no qualification.' }
    if ($actual.complete -ne $true -or
        [string]$actual.signed_apps -notmatch '^(?i:always)$' -or
        [string]$actual.unsigned_apps -notmatch '^(?i:always|never|prompt)$' -or
        ($Requested -eq 'inherit' -and -not [string]::Equals([string]$actual.unsigned_apps, $ExpectedUnsigned, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($Requested -eq 'signed-only' -and [string]$actual.unsigned_apps -notmatch '^(?i:never)$') -or
        ($Requested -eq 'internal-unsigned-trial' -and [string]$actual.unsigned_apps -notmatch '^(?i:always)$')) {
        throw 'Actual effective Toolkit loading policy differs from the approved target; full startup is not qualified.'
    }
    return $actual
}

if ($TrustPolicy -eq 'internal-unsigned-trial') {
    $internalHelperPath = Join-Path $PSScriptRoot 'InternalUnsignedPreflight.ps1'
    . $internalHelperPath
}

try {
    $preflightCode = 'recovery_storage_isolation_unproven'
    [void](Assert-RecoveryLocalPath $startupPath -New)
    [void](Assert-RecoveryLocalPath $runtimePath -New)
    [void](Assert-RecoveryLocalPath $workflowRootPath -New)
    [void](Assert-RecoveryLocalPath $lastSessionPath -New)
    $preflightRecord.recovery_isolation = Read-RecoveryIsolationSources
    if ($JavaOnlyDiagnostic) {
        if ($TrustPolicy -ne 'inherit') {
            $preflightCode = 'java_only_cannot_apply_trust_policy'
            throw 'Java-only diagnostics cannot apply a nondefault Toolkit loading policy.'
        }
        $preflightRecord.status = 'preflight_passed_not_started'
        $preflightRecord.next_action = 'Java-only diagnostic only; native DLL loading and engineering qualification remain false.'
    } else {
        $preflightCode = 'native_signature_unobservable'
        $dllPath = Join-Path $installedPath 'creo_cli_sketch.dll'
        $signature = Get-AuthenticodeSignature -LiteralPath $dllPath -ErrorAction Stop
        $observedSigner = if ($null -eq $signature.SignerCertificate) { $null } else { $signature.SignerCertificate.Thumbprint }
        $preflightRecord.native_signature = [ordered]@{
            path = $dllPath; sha256 = (Get-FileHash -LiteralPath $dllPath -Algorithm SHA256).Hash.ToLowerInvariant()
            status = [string]$signature.Status; signature_type = [string]$signature.SignatureType
            authenticode_verified = ([string]$signature.Status -eq 'Valid')
            signer_thumbprint = $observedSigner
            signer_subject = if ($null -eq $signature.SignerCertificate) { $null } else { $signature.SignerCertificate.Subject }
            timestamp_present = ($null -ne $signature.TimeStamperCertificate)
            trust_basis = 'Windows Authenticode Status, not existence of an unlock stamp or timestamp certificate'
        }
        if ($preflightRecord.native_signature.sha256 -ne $bundleManifest.files.'creo_cli_sketch.dll'.sha256) { throw 'The native DLL changed during signature observation; no launch.' }
        if ($TrustPolicy -eq 'internal-unsigned-trial') {
            $preflightCode = 'internal_trial_binding_required'
            [void](Require-InternalTrialBinding)
            $preflightCode = 'internal_trial_expected_unsigned_required'
            if ([string]$signature.Status -ne 'NotSigned' -or $null -ne $observedSigner -or
                -not [string]::IsNullOrEmpty($ExpectedNativeSignerThumbprint)) {
                throw 'Internal unsigned trial accepts only the pinned NotSigned DLL; it does not authorize another signer or unknown signature state.'
            }
            $preflightRecord.native_signature.publisher_pin_matched = $false
            $preflightRecord.native_signature.acceptance_basis = 'Explicit internal unsigned trial with exact ordinary-unlocked source/component binding; not signature verification.'
            $preflightCode = 'internal_trial_isolation_unproven'
            [void](Require-InternalIsolation)
        } else {
        if ([string]$signature.Status -ne 'Valid' -or [string]$signature.SignatureType -ne 'Authenticode') {
            $preflightCode = 'native_authenticode_required'
            throw 'The DLL requires valid authorized Authenticode signing. Prepare a new -cd input, obtain an approved enterprise/CA signature, verify it, then bind its actual signed SHA; do not accept the source dialog.'
        }
        if ($ExpectedNativeSignerThumbprint -notmatch '^[a-fA-F0-9]{40}$') {
            $preflightCode = 'native_signer_authorization_missing'
            throw 'An explicitly approved publisher certificate thumbprint is required; no signer is selected automatically.'
        }
        if (-not [string]::Equals($observedSigner, $ExpectedNativeSignerThumbprint, [System.StringComparison]::OrdinalIgnoreCase)) {
            $preflightCode = 'native_signer_mismatch'
            throw 'The DLL publisher differs from the explicitly approved signer; no launch.'
        }
        $preflightRecord.native_signature.publisher_pin_matched = $true
        }
        $preflightCode = 'configuration_unobservable_or_conflicting'
        $configuration = Read-DeclaredPolicy
        $preflightRecord.inherited_policy = $configuration.values
        $preflightRecord.login_configuration_directory = $configuration.login_directory
        if ($TrustPolicy -in @('signed-only', 'internal-unsigned-trial')) {
            $proposed = @{ open_protk_signed_apps = 'always'; open_protk_unsigned_apps = $(if ($TrustPolicy -eq 'internal-unsigned-trial') { 'always' } else { 'never' }) }
            if ($TrustPolicy -eq 'internal-unsigned-trial' -and $preflightRecord.internal_trial.policy_profile -eq 'creo-13.4.1.0-unsigned-native') {
                $proposed = @{ open_protk_unsigned_apps = 'always' }
            }
            $preflightRecord.proposed_policy = $proposed
            foreach ($key in $proposed.Keys) {
                if ($configuration.locked.ContainsKey($key) -and $configuration.locked[$key] -ne $proposed[$key]) {
                    $preflightCode = 'protected_configuration_conflict'
                    throw 'Protected config.sup conflicts with the proposed local policy; administrator action is required. No override or launch.'
                }
            }
            $preflightRecord.next_action = if ($TrustPolicy -eq 'internal-unsigned-trial') {
                if ($preflightRecord.internal_trial.policy_profile -eq 'creo-13.4.1.0-unsigned-native') {
                    'This exact installed-version profile applies unsigned Always to all unsigned TOOLKIT apps in the new isolated owned session, not one DLL. The signed option is unsupported and unverified; no signed-policy default is inferred.'
                } else { 'Explicit internal unsigned trial requires informed user approval for all signed and unsigned TOOLKIT apps in this new isolated owned session; exact component pins are not a DLL loading-policy allowlist.' }
            } else { 'Explicit signed-only option requires prior user approval. It affects all signed Toolkit apps in this new owned session, not one DLL or one certificate.' }
        } elseif ($configuration.values.open_protk_signed_apps -ne 'always') {
            $preflightCode = 'inherited_policy_not_proven_noninteractive'
            throw 'Inherited signed loading policy is not proven Always. Resolve declared deployment policy or obtain approval for the explicit private signed-only option; no launch into a prompt.'
        }
        $preflightRecord.status = 'preflight_passed_not_started'
    }
    if ($PreflightOnly) {
        Save-DeploymentPreflight
        $preflightRecord | ConvertTo-Json -Depth 16
        exit 0
    }
    $preflightRecord.next_action = 'Proceed only with this declared new owned generation; actual loaded identity and effective session policy still require verification.'
    Save-DeploymentPreflight
} catch {
    $preflightRecord.status = 'not_started'
    $preflightRecord.failure = [ordered]@{ code = $preflightCode; phase = 'deployment_preflight'; message = [string]$_.Exception.Message; automatic_retry = $false }
    $preflightRecord.next_action = if ($preflightCode -eq 'recovery_storage_isolation_unproven') {
        'Preserve all previous recovery data and this attempt. Resolve the protected recovery/cache source conflict for a new owned runtime; do not delete data, disable recording or click a recovery dialog.'
    } elseif ($TrustPolicy -eq 'internal-unsigned-trial') {
        'Retain this attempt. Resolve the exact binding, ordinary unlock, isolation or protected-policy failure; do not switch profiles, accept a source prompt or bypass administrator settings.'
    } else { 'Retain this report. Supply a legitimate approved signer and noninteractive declared policy; no certificate import, unsigned-Always setting or desktop fallback is performed.' }
    try { Save-DeploymentPreflight } catch { $preflightRecord.report_write_failure = 'Could not create new preflight report; prior files were not overwritten.' }
    $preflightRecord | ConvertTo-Json -Depth 16
    exit 1
}
$javaRelative = [System.IO.Path]::GetRelativePath($startupPath, (Join-Path $installedPath 'creo-cli-service.jar'))
$nativeRelative = [System.IO.Path]::GetRelativePath($startupPath, (Join-Path $installedPath 'creo_cli_sketch.dll'))
$textRelative = [System.IO.Path]::GetRelativePath($startupPath, $installedPath)
foreach ($registryValue in @($javaRelative, $nativeRelative, $textRelative)) {
    if ([System.IO.Path]::IsPathRooted($registryValue) -or $registryValue -match '[^\x21-\x7e]') {
        throw 'Use ASCII component/startup leaf directory names under one common parent. The common parent may contain Chinese characters and spaces; relative registry fields must be ASCII without whitespace.'
    }
}
# Creo registry path parsing is separately constrained from Windows Unicode filenames.
# Bind the declared installation through relative fields from this explicit startup directory.
$nativeDelayStart = if ($requireNative) { 'false' } else { 'true' }
$startupRegistry = @"
name creo_cli_sketch
startup dll
exec_file $nativeRelative
text_dir $textRelative
allow_stop true
fail_tol true
delay_start $nativeDelayStart
end
name creo_cli_service
startup otk_java
toolkit object
creo_type parametric
java_app_class $($bundleManifest.java_app_class)
java_app_classpath $javaRelative
java_app_start start
java_app_stop stop
allow_stop true
fail_tol true
delay_start false
end
"@
$portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $portProbe.Start() } finally { $portProbe.Stop() }
[System.IO.Directory]::CreateDirectory($startupPath) | Out-Null
[System.IO.Directory]::CreateDirectory($runtimePath) | Out-Null
[System.IO.Directory]::CreateDirectory($workflowRootPath) | Out-Null
[System.IO.Directory]::CreateDirectory($lastSessionPath) | Out-Null
[System.IO.File]::WriteAllText((Join-Path $startupPath 'protk.dat'), $startupRegistry + "`n", [System.Text.UTF8Encoding]::new($false))
$localPolicyText = ''
if ($requireNative -and $TrustPolicy -in @('signed-only', 'internal-unsigned-trial')) {
    # The explicit option is the caller's assertion of already obtained approval.
    # It is scoped to this new startup directory and never changes global policy.
    $unsignedPolicy = if ($TrustPolicy -eq 'internal-unsigned-trial') { 'always' } else { 'never' }
    $localPolicyText = if ($TrustPolicy -eq 'internal-unsigned-trial' -and $preflightRecord.internal_trial.policy_profile -eq 'creo-13.4.1.0-unsigned-native') {
        "open_protk_unsigned_apps always`n"
    } else { "open_protk_signed_apps always`nopen_protk_unsigned_apps $unsignedPolicy`n" }
}
$localPolicyText += "last_session_directory_path $($preflightRecord.recovery_isolation.configured_directory_value)`nlast_session_retrieval yes`n"
[System.IO.File]::WriteAllText((Join-Path $startupPath 'config.pro'), $localPolicyText, [System.Text.UTF8Encoding]::new($false))
$preflightRecord.local_configuration_written = $true

$childEnvironment = @{
    PRO_JAVA_COMMAND = $javaExecutable
    CREO_CLI_CONFIG_DIR = $runtimePath
    CREO_CLI_SERVICE_PORT = [string]$Port
    PROCESSOR_ARCHITECTURE = 'AMD64'
    PTC_WF_ROOT = $workflowRootPath
}
$beforeStartInstant = [DateTime]::UtcNow
$beforeStart = $beforeStartInstant.ToString('o')
$startupClock = [System.Diagnostics.Stopwatch]::StartNew()
# A separate owned PowerShell log host keeps pipes alive until natural closure.
# Neither process host nor checker uses a command shell or desktop input.
$launchSpecPath = Join-Path $startupPath 'process-launch-spec.json'
$processRecordPath = Join-Path $startupPath 'launcher-process.json'
[ordered]@{
    executable = $creoExecutable; arguments = $launchArguments; working_directory = $startupPath
    environment = $childEnvironment; stdout = (Join-Path $startupPath 'launcher.stdout.log')
    stderr = (Join-Path $startupPath 'launcher.stderr.log'); process_record = $processRecordPath
    completion_record = (Join-Path $startupPath 'launcher-completion.json')
    error_record = (Join-Path $startupPath 'launcher-host-error.json')
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $launchSpecPath -Encoding utf8
if ($TrustPolicy -eq 'internal-unsigned-trial') {
    $preflightRecord.generated_startup_files = @(
        (Get-TrialFile (Join-Path $startupPath 'protk.dat')),
        (Get-TrialFile (Join-Path $startupPath 'config.pro')),
        (Get-TrialFile $launchSpecPath)
    )
}
$hostStart = [System.Diagnostics.ProcessStartInfo]::new()
$hostStart.FileName = Join-Path $PSHOME 'pwsh.exe'; $hostStart.WorkingDirectory = $startupPath
$hostStart.UseShellExecute = $false; $hostStart.CreateNoWindow = $true
# The log host can outlive this checker. Give it its own pipes so it cannot keep
# the checker's caller stdout/stderr open after ready/not_ready has been returned.
# The host sends native output to its independent files and has no console loop.
$hostStart.RedirectStandardOutput = $true; $hostStart.RedirectStandardError = $true
foreach ($argument in @('-NoProfile', '-NonInteractive', '-File', $processHostScript, '-LaunchSpecPath', $launchSpecPath)) {
    $hostStart.ArgumentList.Add($argument)
}
$processHost = [System.Diagnostics.Process]::new(); $processHost.StartInfo = $hostStart
# Windows can also inherit an unused copy of the checker's original pipe even
# when STARTUPINFO points at redirected stdio. Suppress inheritance only during
# this one CreateProcess call, and restore the caller-owned handle flags. We do
# not replace/close handles or take ownership away from .NET Console/SafeHandle.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
public static class CreoStartupPipeInheritance {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GetStdHandle(int id);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint GetFileType(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetHandleInformation(IntPtr handle, out uint flags);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    public static bool Start(Process child) {
        var changed = new Dictionary<IntPtr,uint>();
        try {
            foreach (int id in new int[] {-11,-12}) {
                IntPtr handle=GetStdHandle(id);
                if (handle==IntPtr.Zero || handle==new IntPtr(-1) ||
                    GetFileType(handle)!=3 || changed.ContainsKey(handle)) continue;
                uint flags;
                if (!GetHandleInformation(handle,out flags))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                if ((flags&1)==0) continue;
                changed.Add(handle,flags);
                if (!SetHandleInformation(handle,1,0))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return child.Start();
        } finally {
            foreach (var entry in changed)
                if (!SetHandleInformation(entry.Key,1,entry.Value&1))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
'@
try {
    $recoverySources = Read-RecoveryIsolationSources
    if (($recoverySources | ConvertTo-Json -Depth 16 -Compress) -ne ($preflightRecord.recovery_isolation | ConvertTo-Json -Depth 16 -Compress)) {
        throw 'Recovery configuration or PSF sources changed before dispatch.'
    }
    Require-OwnedRecoveryDirectories -Empty
    $preflightRecord.recovery_isolation.empty_before_dispatch = $true
    if ($TrustPolicy -eq 'internal-unsigned-trial') {
        $admittedTrial = $preflightRecord.internal_trial | ConvertTo-Json -Depth 16 -Compress
        $admittedIsolation = $preflightRecord.internal_isolation | ConvertTo-Json -Depth 16 -Compress
        [void](Require-InternalTrialBinding)
        [void](Require-InternalIsolation)
        foreach ($generated in $preflightRecord.generated_startup_files) { [void](Require-TrialFile $generated $generated.path) }
        if (($preflightRecord.internal_trial | ConvertTo-Json -Depth 16 -Compress) -ne $admittedTrial -or
            ($preflightRecord.internal_isolation | ConvertTo-Json -Depth 16 -Compress) -ne $admittedIsolation) {
            throw 'Internal trial deployment or isolation sources changed before dispatch.'
        }
    }
    foreach ($payload in $bundleManifest.files.PSObject.Properties) {
        $beforeLaunchHash = (Get-FileHash -LiteralPath (Join-Path $installedPath $payload.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($beforeLaunchHash -ne $payload.Value.sha256) { throw 'Declared component changed after preflight; no process launch.' }
    }
} catch {
    $preflightPath = $startupPath + '.predispatch-' + [guid]::NewGuid().ToString('N') + '.json'
    $preflightRecord.report_path = $preflightPath
    $preflightRecord.status = 'not_started'
    $preflightRecord.failure = @{
        code = $(if ($TrustPolicy -eq 'internal-unsigned-trial') { 'internal_deployment_changed_before_launch' } else { 'component_changed_before_launch' })
        phase = 'deployment_predispatch'
        message = 'Declared components, configuration or generated startup files changed before process creation; preserve all files and start a newly inspected attempt.'
        automatic_retry = $false
    }
    Save-DeploymentPreflight
    $preflightRecord | ConvertTo-Json -Depth 16
    exit 1
}
$processHostStarted = $false
try {
    $processHostStarted = [CreoStartupPipeInheritance]::Start($processHost)
    if (-not $processHostStarted) { throw 'The process host did not establish a new process association.' }
    $hostBootstrapOut = [System.IO.FileStream]::new((Join-Path $startupPath 'process-host-bootstrap.stdout.log'), [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $hostBootstrapError = [System.IO.FileStream]::new((Join-Path $startupPath 'process-host-bootstrap.stderr.log'), [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $hostOutCopy = $processHost.StandardOutput.BaseStream.CopyToAsync($hostBootstrapOut)
    $hostErrorCopy = $processHost.StandardError.BaseStream.CopyToAsync($hostBootstrapError)
    while (-not (Test-Path -LiteralPath $processRecordPath -PathType Leaf) -and $startupClock.Elapsed.TotalSeconds -lt $WaitSeconds) {
        if (Test-Path -LiteralPath (Join-Path $startupPath 'launcher-host-error.json')) { throw 'The owned process host failed before publishing its launcher record; retain its error record.' }
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $processRecordPath -PathType Leaf)) { throw 'The owned process host did not publish its launcher record before the deadline; no process was killed.' }
    $processRecord = Get-Content -LiteralPath $processRecordPath -Raw -Encoding utf8 | ConvertFrom-Json
    $ownedProcess = [pscustomobject]@{ Id = [int]$processRecord.launcher_pid }
    $birth = $processRecord.launcher_creation_filetime
} catch {
    $bootstrapHostId = $null
    try { $bootstrapHostId = $processHost.Id; $processHostStarted = $true } catch { }
    $bootstrapFailure = [ordered]@{
        status = 'not_ready'; started_before_utc = $beforeStart
        failure = @{ phase = 'launcher_bootstrap'; code = 'launcher_record_unknown'
            error_type = $_.Exception.GetType().FullName
            message = ([string]$_.Exception.Message).Substring(0, [Math]::Min(512, ([string]$_.Exception.Message).Length))
            automatic_retry = $false; processes_stopped = @() }
        process_host_started = $processHostStarted
        process_host_pid = $bootstrapHostId
        native_process_identity = 'unknown'; native_load_verified = $false
        installation = $installedPath; startup = $startupPath; runtime = $runtimePath
        launch_spec = $launchSpecPath; launcher_record = $processRecordPath
        argument_transport = 'ProcessStartInfo.ArgumentList'
        desktop_input_count = 0; cua_input_count = 0; session_readiness_attempts = 0
        require_native = $requireNative
        qualification = $(if ($TrustPolicy -eq 'internal-unsigned-trial') { 'internal_unsigned_full_components_automatic_startup' } elseif ($requireNative) { 'full_components_automatic_startup' } else { 'java_only_diagnostic_not_engineering_acceptance' })
        deployment_preflight = $preflightRecord; recovery_isolation = $preflightRecord.recovery_isolation
        recovery_isolation_verified = $false; deployment_policy_verified = $false
        next_action = 'Preserve this attempt, late launcher records and logs. Process creation outcome is unknown; no CAD retry, recovery action or termination was performed.'
    }
    $bootstrapRecordPath = Join-Path $startupPath 'launch.json'
    try {
        $stream = [IO.FileStream]::new($bootstrapRecordPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try { $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($bootstrapFailure | ConvertTo-Json -Depth 16) + "`n"); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    } catch { $bootstrapFailure.report_write_failure = 'Could not create the bootstrap result; existing files were preserved.' }
    $bootstrapFailure | ConvertTo-Json -Depth 16
    exit 1
}
$record = [ordered]@{
    status = 'process_started_loading_not_yet_verified'
    started_before_utc = $beforeStart
    launcher_pid = $ownedProcess.Id
    launcher_creation_filetime = $birth
    executable = $creoExecutable
    psf = $declaredPsfArgument
    launch_arguments = $launchArguments
    initial_model = $initialModelRecord
    process_host_pid = $processHost.Id
    process_host_stdio = 'redirected_away_from_checker_outer_pipes'
    argument_transport = 'ProcessStartInfo.ArgumentList'
    java_executable = $javaExecutable
    installation = $installedPath
    startup = $startupPath
    runtime = $runtimePath
    port = $Port
    manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    startup_registry_sha256 = (Get-FileHash -LiteralPath (Join-Path $startupPath 'protk.dat') -Algorithm SHA256).Hash.ToLowerInvariant()
    registry_path_base = $startupPath
    registry_paths = @{ java = $javaRelative; native = $nativeRelative; text = $textRelative }
    next_action = 'Wait for owned-process identity and authenticated native readiness; never use Auxiliary Applications as a fallback.'
    cli_history_directory_changed = $false
    desktop_input_count = 0
    cua_input_count = 0
    headless = $false
    session_readiness_attempts = 0
    require_native = $requireNative
    qualification = if ($TrustPolicy -eq 'internal-unsigned-trial') { 'internal_unsigned_full_components_automatic_startup' } elseif ($requireNative) { 'full_components_automatic_startup' } else { 'java_only_diagnostic_not_engineering_acceptance' }
    native_load_verified = $false
    deployment_preflight = $preflightRecord
    deployment_policy_verified = $false
    applicable_policy_verified = $false
    signed_apps_verified = $false
    full_policy_option_set_verified = $false
    recovery_isolation = $preflightRecord.recovery_isolation
    recovery_isolation_verified = $false
    recovery_window_observations = @()
    observations = @()
}

function Save-Launch {
    $record.elapsed_seconds = $startupClock.Elapsed.TotalSeconds
    $record | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $startupPath 'launch.json') -Encoding utf8
}
function Same-Path([string]$Left, [string]$Right) {
    return [string]::Equals([System.IO.Path]::GetFullPath($Left), [System.IO.Path]::GetFullPath($Right), [System.StringComparison]::OrdinalIgnoreCase)
}
function Owned-Process([int]$Id, [string]$Executable) {
    $found = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction Stop
    if ($null -eq $found -or $null -eq $found.CreationDate -or
        $found.CreationDate.ToUniversalTime() -lt $beforeStartInstant -or
        [string]::IsNullOrEmpty($found.ExecutablePath) -or -not (Same-Path $found.ExecutablePath $Executable)) {
        throw 'The reported process is not a newly started declared executable; existing instances are preserved.'
    }
    return $found
}
function Read-StartupBlocker {
    foreach ($trail in @(Get-ChildItem -LiteralPath $startupPath -Filter 'trail.txt.*' -File)) {
        $tail = (Get-Content -LiteralPath $trail.FullName -Tail 120 -ErrorAction SilentlyContinue) -join "`n"
        if ($tail -match 'permission_request_dlg: warning' -and $tail -match 'unknown source') {
            return [ordered]@{ code = 'external_trust_authorization_required'; evidence = $trail.FullName; source = 'owned startup trail, no UI inspection'; }
        }
    }
    return $null
}
function Test-NativeDiagnosticStop([object]$Health) {
    # The disabled diagnostic DTO has no status/blocked members. Read only this
    # optional object safely; required health/identity/readiness fields stay strict.
    $diagnostic = $null
    if ($Health -is [System.Collections.IDictionary]) {
        if ($Health.Contains('native_diagnostic')) { $diagnostic = $Health['native_diagnostic'] }
    } elseif ($Health -is [pscustomobject]) {
        $property = $Health.PSObject.Properties['native_diagnostic']
        if ($null -ne $property) { $diagnostic = $property.Value }
    } else { throw 'The service health observation is not an object.' }
    if ($null -eq $diagnostic) { return $false }
    if ($diagnostic -isnot [System.Collections.IDictionary] -and $diagnostic -isnot [pscustomobject]) {
        throw 'The native diagnostic observation is not an object.'
    }
    $values = @{}
    foreach ($name in @('stopped', 'status', 'blocked')) {
        $values[$name] = $null
        if ($diagnostic -is [System.Collections.IDictionary]) {
            if ($diagnostic.Contains($name)) { $values[$name] = $diagnostic[$name] }
        } else {
            $property = $diagnostic.PSObject.Properties[$name]
            if ($null -ne $property) { $values[$name] = $property.Value }
        }
    }
    foreach ($name in @('stopped', 'blocked')) {
        if ($null -ne $values[$name] -and $values[$name] -isnot [bool]) {
            throw "The native diagnostic $name observation is not a boolean."
        }
    }
    if ($null -ne $values['status'] -and $values['status'] -isnot [string]) {
        throw 'The native diagnostic status observation is not a string.'
    }
    return ($values['stopped'] -eq $true -or $values['status'] -eq 'stopped' -or $values['blocked'] -eq $true)
}

Save-Launch
$endpoint = "http://127.0.0.1:$Port"
$nativeImageFile = Join-Path $runtimePath 'native-loaded-image.txt'
$tokenFile = Join-Path $runtimePath 'service-token'
$hostExecutable = Join-Path $launchCreoRoot 'Common Files/x86e_win64/obj/xtop.exe'
$readyHealth = $null
try {
    while ($true) {
        # Preparation/bootstrap can exhaust the native-readiness budget. Still
        # report an already-observed source prompt before a generic deadline;
        # this reads only owned trail files and never accepts a dialog or calls CAD.
        $blocker = Read-StartupBlocker
        if ($null -ne $blocker) {
            $record.external_blocker = $blocker
            throw 'Creo requires external trust authorization before loading the native DLL. Security policy and the dialog were not changed.'
        }
        if ($startupClock.Elapsed.TotalSeconds -ge $WaitSeconds) { break }
        $observation = [ordered]@{ at_utc = [DateTime]::UtcNow.ToString('o'); phase = 'process_only_health'; status = 'unavailable' }
        try {
            $health = Invoke-RestMethod -Uri "$endpoint/health" -TimeoutSec 2 -ErrorAction Stop
            $record.health = $health
            if ($health.ok -ne $true -or $health.service -ne 'creo-cli' -or $health.protocol -ne 2 -or
                $health.runtime_class -ne $bundleManifest.java_app_class -or
                $health.source_sha256 -ne $bundleManifest.component_source_sha256 -or
                -not (Same-Path $health.runtime_configuration.state_directory $runtimePath)) {
                throw 'Service identity differs from the declared installation or new runtime directory.'
            }
            $observation.status = 'loaded'
            $observation.startup_state = $health.startup_state
            $observation.service_instance_id = $health.service_instance_id
            if ($health.startup_state -in @('failed', 'stop_failed')) { throw 'The service reports failed startup or stop; retain service.log.' }
            if (Test-NativeDiagnosticStop $health) {
                throw 'The service reports a native diagnostic stop; no CAD readiness call is permitted.'
            }
            if ($health.startup_state -eq 'ready' -and $health.toolkit_pump_running -eq $true -and
                (-not $requireNative -or (Test-Path -LiteralPath $nativeImageFile -PathType Leaf)) -and
                (Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
                $javaProcess = Owned-Process ([int]$health.process_id) $javaExecutable
                $ancestor = $javaProcess
                $chain = @()
                for ($i = 0; $i -lt 16 -and $null -ne $ancestor; $i++) {
                    $chain += [int]$ancestor.ProcessId
                    if (-not [string]::IsNullOrEmpty($ancestor.ExecutablePath) -and (Same-Path $ancestor.ExecutablePath $hostExecutable)) { break }
                    $ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$($ancestor.ParentProcessId)" -ErrorAction Stop
                }
                $nativeId = [int]$chain[-1]
                $nativeProcess = Owned-Process $nativeId $hostExecutable
                $launcherNow = Get-Process -Id $ownedProcess.Id -ErrorAction Stop
                if ([string]$launcherNow.StartTime.ToUniversalTime().ToFileTimeUtc() -ne $birth -or
                    $nativeProcess.CommandLine -notmatch ('(?:^|\s)-ppid\s+' + [regex]::Escape([string]$ownedProcess.Id) + '(?:\s|$)')) {
                    throw 'The native host is not bound to this exact launcher generation.'
                }
                $modulePaths = @((Get-Process -Id $nativeId -ErrorAction Stop).Modules | ForEach-Object { $_.FileName })
                if ($requireNative) {
                    $nativeImage = @(Get-Content -LiteralPath $nativeImageFile)
                    if ($nativeImage.Count -ne 2 -or $nativeImage[0] -ne [string]$nativeId -or
                        -not (Same-Path $nativeImage[1] (Join-Path $installedPath 'creo_cli_sketch.dll'))) {
                        throw 'The native DLL handshake differs from the declared installation or owned host.'
                    }
                    if (-not ($modulePaths | Where-Object { Same-Path $_ (Join-Path $installedPath 'creo_cli_sketch.dll') })) {
                        throw 'The declared native DLL is not in the owned host module inventory.'
                    }
                    $record.native_load_verified = $true
                } elseif (Test-Path -LiteralPath $nativeImageFile) {
                    throw 'Java-only diagnostic unexpectedly has a native DLL handshake; preserve and refuse.'
                }
                $record.runtime_pin = [ordered]@{
                    java_pid = [int]$health.process_id; native_pid = $nativeId; chain = $chain
                    service_instance_id = $health.service_instance_id
                    process_creations = @{}
                }
                foreach ($processId in $chain) {
                    $entry = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop
                    $preciseProcess = Get-Process -Id $processId -ErrorAction Stop
                    $record.runtime_pin.process_creations[[string]$processId] = [string]$preciseProcess.StartTime.ToUniversalTime().ToFileTimeUtc()
                }
                $readyHealth = $health
                $observation.status = if ($requireNative) { 'owned_processes_and_native_dll_verified' } else { 'owned_java_only_diagnostic' }
            }
        } catch {
            # Only transport absence can be retried. Identity/startup/diagnostic failures
            # are terminal; they must never lead to probing the toolkit or another seat.
            if ($_.Exception -is [System.Net.Http.HttpRequestException] -or
                $_.Exception -is [System.Threading.Tasks.TaskCanceledException] -or
                $_.Exception -is [System.Net.WebException]) {
                $observation.status = 'no_health_response'
            } else { throw }
        }
        $record.observations += $observation
        Save-Launch
        if ($null -ne $readyHealth) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $readyHealth) {
        throw 'Automatic startup did not become ready before its deadline. Inspect retained launcher/service/trail logs and external license/trust prerequisites; no desktop fallback was attempted.'
    }
    Require-NoOwnedRecoveryDialog 'before_authenticated_readiness'
    # Exactly one authenticated CAD read, only after process-only admission. A timeout
    # may mean the call started; preserve it and never retry or dispatch more CAD here.
    $secret = [System.IO.File]::ReadAllText($tokenFile).Trim()
    if ($secret -notmatch '^[a-f0-9]{64}$') { throw 'The new service credential is malformed.' }
    $headers = @{ 'X-Creo-Cli-Token' = $secret; 'X-Creo-Cli-Wait-Ms' = [string]($SessionTimeoutSeconds * 1000 - 2000); 'X-Creo-Cli-Invocation-Id' = ('owned-startup-' + [guid]::NewGuid().ToString('N')) }
    $record.status = 'owned_identity_verified_session_readiness_started'
    $record.session_readiness_attempts = 1
    Save-Launch
    $session = Invoke-RestMethod -Uri "$endpoint/session" -Headers $headers -TimeoutSec $SessionTimeoutSeconds -ErrorAction Stop
    $secret = $null
    $headers = $null
    $record.session_readiness = $session
    if ($session.ok -ne $true -or $session.session_reachable -ne $true -or
        $session.creation_api -ne $true -or ($requireNative -and $session.native_sketch_available -ne $true) -or
        (-not $requireNative -and $session.native_sketch_available -ne $false)) {
        throw 'Authenticated native readiness failed; retain the response and do not retry automatically.'
    }
    $record.recovery_configuration = Require-RecoveryReadback $session
    Require-OwnedRecoveryDirectories
    if ($requireNative) {
        $observedPolicy = Require-EffectiveDeploymentPolicy $session $TrustPolicy ([string]$preflightRecord.inherited_policy.open_protk_unsigned_apps) ([string]$preflightRecord.internal_trial.policy_profile)
        $record.deployment_policy_verified = ($observedPolicy.complete -eq $true)
        $record.full_policy_option_set_verified = ($observedPolicy.complete -eq $true)
        $record.signed_apps_verified = ($observedPolicy.complete -eq $true -and [string]$observedPolicy.signed_apps -match '^(?i:always)$')
        $record.applicable_policy_verified = $true
        $record.effective_deployment_policy = $observedPolicy
    }
    # The one readiness call must not change which generation owns this startup.
    $afterHealth = Invoke-RestMethod -Uri "$endpoint/health" -TimeoutSec 2 -ErrorAction Stop
    if ($afterHealth.service_instance_id -ne $readyHealth.service_instance_id -or $afterHealth.process_id -ne $readyHealth.process_id) {
        throw 'The service generation changed during readiness verification.'
    }
    foreach ($payload in $bundleManifest.files.PSObject.Properties) {
        $observedHash = (Get-FileHash -LiteralPath (Join-Path $installedPath $payload.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($observedHash -ne $payload.Value.sha256) { throw 'Declared component bytes changed during startup verification.' }
    }
    if ($null -ne $initialModelRecord) {
        $afterModelHash = (Get-FileHash -LiteralPath $initialModelRecord.path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($afterModelHash -ne $initialModelRecord.sha256) { throw 'The exact InitialModel bytes changed during startup; preserve the file and this generation.' }
        $initialModelRecord.input_bytes_unchanged_after_start = $true
    }
    Require-NoOwnedRecoveryDialog 'after_authenticated_readiness'
    $record.recovery_isolation_verified = $true
    $record.status = 'ready'
    $record.health = $afterHealth
    $record.next_action = 'Use the returned runtime_pin and declared token-file path for public CLI doctor/context; use this owned generation only.'
    Save-Launch
    $record | ConvertTo-Json -Depth 16
    exit 0
} catch {
    $record.status = 'not_ready'
    $record.failure = [ordered]@{
        phase = if ($record.session_readiness_attempts -eq 0) { 'startup_process_only' } else { 'authenticated_session_readiness' }
        message = if ($record.session_readiness_attempts -eq 0) { [string]$_.Exception.Message } else { 'Native readiness did not complete successfully; inspect retained response and logs. No automatic CAD retry.' }
        automatic_retry = $false
        processes_stopped = @()
    }
    $record.next_action = 'Retain this generation and evidence. Resolve declared external prerequisites independently; do not use desktop input or claim automatic startup passed.'
    Save-Launch
    $record | ConvertTo-Json -Depth 16
    exit 1
}
