# Internal helpers for the explicit, nondefault internal-unsigned-trial startup.
# This file performs file/environment checks only; it never starts Creo or unlocks.
function Assert-RegularLocalPath([string]$Path, [switch]$MayBeMissing) {
    $resolved = Resolve-OwnedPath $Path
    $cursor = $resolved
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $entry = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Internal trial paths cannot cross links or reparse points.'
            }
        } elseif ($cursor -eq $resolved -and -not $MayBeMissing) {
            throw 'A pinned internal trial file is missing.'
        }
        $parent = [System.IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $resolved
}

function Get-TrialFile([string]$Path) {
    $resolved = Assert-RegularLocalPath $Path
    $file = Get-Item -LiteralPath $resolved -Force -ErrorAction Stop
    if ($file.PSIsContainer) { throw 'A pinned internal trial source must be a regular file.' }
    return [ordered]@{
        path = $resolved; sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = $file.Length
    }
}

function Require-TrialFile([object]$Expected, [string]$AtPath) {
    if ($null -eq $Expected -or [string]$Expected.sha256 -notmatch '^[a-f0-9]{64}$' -or
        $null -eq $Expected.bytes -or [long]$Expected.bytes -lt 1) {
        throw 'Internal trial file binding is missing its exact SHA-256 or size.'
    }
    $expectedPath = Resolve-OwnedPath ([string]$Expected.path)
    if (-not [string]::IsNullOrEmpty($AtPath) -and
        -not [string]::Equals($expectedPath, (Resolve-OwnedPath $AtPath), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Internal trial file path differs from its reviewed binding.'
    }
    $actual = Get-TrialFile $expectedPath
    if ($actual.sha256 -ne $Expected.sha256 -or $actual.bytes -ne [long]$Expected.bytes) {
        throw 'Internal trial file bytes differ from their reviewed binding.'
    }
    return $actual
}

function Require-InternalTrialBinding {
    if ($ExpectedInternalTrialBindingSha256 -notmatch '^[a-f0-9]{64}$' -or
        [string]::IsNullOrEmpty($InternalTrialBinding)) {
        throw 'Internal trial requires its explicitly pinned binding file and expected SHA-256.'
    }
    $record = Get-TrialFile $InternalTrialBinding
    if ($record.sha256 -ne $ExpectedInternalTrialBindingSha256) {
        throw 'Internal trial binding differs from the explicitly reviewed SHA-256.'
    }
    $binding = Get-Content -LiteralPath $record.path -Raw -Encoding utf8 | ConvertFrom-Json
    if ($binding.schema_version -ne '1.0' -or $binding.mode -ne 'internal-unsigned-trial' -or
        $binding.source_commit -notmatch '^[a-f0-9]{40}$' -or
        $binding.component_source_sha256 -ne $bundleManifest.component_source_sha256 -or
        $binding.native_source_fingerprint -notmatch '^[a-f0-9]{64}$') {
        throw 'Internal trial source, mode or component fingerprint is not completely bound.'
    }
    $names = @($binding.files.PSObject.Properties.Name | Sort-Object)
    if ($names.Count -ne 3 -or @($names | Where-Object { $_ -notin @('creo-cli-service.jar', 'creo-cli.exe', 'creo_cli_sketch.dll') }).Count) {
        throw 'Internal trial must bind exactly the EXE, JAR and DLL.'
    }
    $observed = [ordered]@{}
    foreach ($name in $names) {
        $componentPath = if ($name -eq 'creo-cli.exe') { [string]$binding.files.$name.path } else { Join-Path $installedPath $name }
        $observed[$name] = Require-TrialFile $binding.files.$name $componentPath
        if ($name -ne 'creo-cli.exe' -and $observed[$name].sha256 -ne $bundleManifest.files.$name.sha256) {
            throw 'Internal trial components differ from their installation manifest.'
        }
    }
    $registry = Require-TrialFile $binding.registry $registryPath
    $psf = Require-TrialFile $binding.psf $creoPsf
    $hooks = [ordered]@{}
    foreach ($relative in @('Common Files/applications/simulate/install/nt/pro_mech_env.bat', 'Common Files/x86e_win64/nms/nmsd.exe', 'Common Files/x86e_win64/obj/xtop.exe')) {
        $hooks[$relative] = Get-TrialFile (Join-Path $launchCreoRoot $relative)
    }
    $policyProfile = if ($null -eq $binding.PSObject.Properties['policy_profile']) { 'all-options' } else { [string]$binding.policy_profile }
    if ($policyProfile -notin @('all-options', 'creo-13.4.1.0-unsigned-native')) { throw 'Unknown internal policy profile; no launch.' }
    $profileQualification = $null
    if ($policyProfile -eq 'creo-13.4.1.0-unsigned-native') {
        $profileQualification = Require-UnsignedNative134Profile $binding
    }
    $preparationIdentity = Require-TrialFile $binding.native_preparation ''
    $preparation = Get-Content -LiteralPath $preparationIdentity.path -Raw -Encoding utf8 | ConvertFrom-Json
    if ($preparation.status -ne 'ordinary_unlocked_internal_unsigned' -or
        $preparation.unlock_mode -ne '-c' -or $preparation.toolkit_unlocked -ne $true -or
        $preparation.authenticode_status -ne 'NotSigned' -or
        $preparation.source_fingerprint -ne $binding.native_source_fingerprint -or
        $preparation.source_commit -notmatch '^[a-f0-9]{40}$' -or
        $null -eq $preparation.ordinary_unlock -or $preparation.ordinary_unlock.exit_code -ne 0 -or
        $preparation.ordinary_unlock.success_marker -ne 'Successfully unlocked application.' -or
        $preparation.dll.sha256 -ne $observed['creo_cli_sketch.dll'].sha256 -or
        [long]$preparation.dll.bytes -ne $observed['creo_cli_sketch.dll'].bytes) {
        throw 'Internal trial requires exact ordinary -c unlock evidence; -cd or a stamp is insufficient.'
    }
    # Pinning the evidence is not independently proving a license or signature.
    $preflightRecord.internal_trial = [ordered]@{
        binding = $record; source_commit = $binding.source_commit; files = $observed
        registry = $registry; psf = $psf; native_preparation = $preparationIdentity
        vendor_launch_hooks = $hooks
        policy_profile = $policyProfile; policy_profile_qualification = $profileQualification
        process_host = (Get-TrialFile $processHostScript)
        unlock_mode = '-c'; toolkit_unlocked = $true; authenticode_verified = $false
        signature_requirement = 'Expected NotSigned only; no signed-route verification is bypassed.'
        policy_scope = $(if ($policyProfile -eq 'creo-13.4.1.0-unsigned-native') {
            'Unsigned Always affects all unsigned TOOLKIT apps in this new owned session, not a DLL allowlist. Signed option unsupported and unverified; no signed-policy default is inferred.'
        } else { 'All signed and unsigned TOOLKIT apps in this new owned session; not a DLL allowlist.' })
        qualification = 'Pinned preparation and isolation preflight only; actual full component loading remains unverified.'
    }
    return $binding
}

function Require-UnsignedNative134Profile([object]$Binding) {
    $hostPath = Join-Path $launchCreoRoot 'Common Files/x86e_win64/obj/xtop.exe'
    $hostIdentity = Get-TrialFile $hostPath
    $version = (Get-Item -LiteralPath $hostPath -Force -ErrorAction Stop).VersionInfo
    if ($version.ProductVersion -ne '13.4.1.0' -or $version.FileVersion -ne '41,0,2026,163') {
        throw 'The bounded unsigned-native policy profile requires exact installed Creo 13.4.1.0 / 41,0,2026,163.'
    }
    $catalogPath = Join-Path $launchCreoRoot 'Common Files/help/reference/pma/usascii/configoptions.pdf'
    $catalog = Require-TrialFile $Binding.configuration_catalog $catalogPath
    if ($catalog.sha256 -ne '61c54d38d025d416dc660f070b4634a6c603cbe11f71cc25a1fe395d2f73b649') {
        throw 'The bounded policy profile requires the reviewed installed 13.4.1.0 primary configuration catalog.'
    }
    return [ordered]@{
        profile = 'creo-13.4.1.0-unsigned-native'; native_host = $hostIdentity
        product_version = $version.ProductVersion; file_version = $version.FileVersion
        configuration_catalog = $catalog; catalog_scope = 'Installed primary English catalog, page 153: open_protk_unsigned_apps; signed option absent.'
        applicable_configuration = @{ open_protk_unsigned_apps = 'always' }
        signed_apps_verified = $false; full_policy_option_set_verified = $false
        acceptance_condition = 'Pinned sole ordinary-unlocked NotSigned DLL and owned JAR; actual unsigned Always plus classified unavailable signed option. No signed-default inference.'
    }
}

function Get-InternalConfigurationRoots {
    $roots = @([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile))
    if ($loginConfigurationExplicit) { $roots += (Resolve-OwnedPath $LoginConfigurationDirectory) }
    if (-not [string]::IsNullOrEmpty($env:HOME)) { $roots += (Resolve-OwnedPath $env:HOME) }
    if (-not [string]::IsNullOrEmpty($env:HOMEDRIVE) -and -not [string]::IsNullOrEmpty($env:HOMEPATH)) {
        $roots += (Resolve-OwnedPath ($env:HOMEDRIVE + $env:HOMEPATH))
    }
    return @($roots | Select-Object -Unique)
}

function Get-InternalPluginRoots([string[]]$ProgramDataRoots = @([Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData), $env:ProgramData)) {
    $pluginRoots = @(); $visited = 0
    foreach ($root in @($ProgramDataRoots | Where-Object { -not [string]::IsNullOrEmpty($_) } | Select-Object -Unique)) {
        $ptcRoot = Join-Path (Resolve-OwnedPath $root) 'PTC'
        if (-not (Test-Path -LiteralPath $ptcRoot)) { continue }
        $queue = [System.Collections.Generic.Queue[string]]::new()
        $queue.Enqueue($ptcRoot)
        while ($queue.Count -gt 0) {
            $directory = $queue.Dequeue(); $visited++
            if ($visited -gt 4096) { throw 'ProgramData PTC plugin discovery exceeds its bounded inspection; no isolated launch.' }
            [void](Assert-RegularLocalPath $directory)
            $underPlugins = $directory -match '(?i)(?:^|[\\/])Plugins(?:[\\/]|$)'
            if ($underPlugins) { $pluginRoots += $directory }
            foreach ($child in @(Get-ChildItem -LiteralPath $directory -Directory -Force -ErrorAction Stop)) {
                # Do not recurse through a junction or silently omit an unreadable plugin source.
                if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw 'A ProgramData PTC directory is a reparse point; plugin isolation is unproven.'
                }
                $queue.Enqueue($child.FullName)
            }
        }
    }
    return @($pluginRoots | Select-Object -Unique)
}

function Get-InternalSourceRoots {
    $roots = @((Join-Path $launchCreoRoot 'Common Files/text'), (Join-Path $launchCreoRoot 'Common Files/x86e_win64/text'))
    foreach ($base in @($roots)) {
        if (Test-Path -LiteralPath $base) {
            [void](Assert-RegularLocalPath $base)
            $roots += @(Get-ChildItem -LiteralPath $base -Directory -Force | ForEach-Object { $_.FullName })
        }
    }
    $roots += @(Get-InternalConfigurationRoots)
    $roots += @(Get-InternalPluginRoots)
    if (-not [string]::IsNullOrEmpty($env:PTC_CREO_ALT_SETTINGS_PATH)) { $roots += (Resolve-OwnedPath $env:PTC_CREO_ALT_SETTINGS_PATH) }
    return @($roots | Select-Object -Unique)
}

function Require-ReviewedTrialRegistry {
    $blocks = @(); $block = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($registryPath)) {
        if ($line -match '^\s*(?:[!#].*)?$') { continue }
        if ($line -match '^\s*end\s*$') {
            if ($block.Count -eq 0) { throw 'Internal trial registry contains an empty application.' }
            $blocks += ,$block; $block = @{}; continue
        }
        if ($line -notmatch '^\s*([a-z_]+)\s+(.+?)\s*$') { throw 'Internal trial registry is malformed.' }
        $key = $Matches[1].ToLowerInvariant(); $value = $Matches[2]
        if ($block.ContainsKey($key)) { throw 'Internal trial registry contains a duplicate field.' }
        $block[$key] = $value
    }
    if ($block.Count -ne 0 -or $blocks.Count -ne 2) { throw 'Internal trial registry must contain exactly two complete reviewed applications.' }
    $native = @($blocks | Where-Object { $_.name -eq 'creo_cli_sketch' })
    $java = @($blocks | Where-Object { $_.name -eq 'creo_cli_service' })
    if ($native.Count -ne 1 -or $java.Count -ne 1 -or $native[0].startup -ne 'dll' -or
        $java[0].startup -ne 'otk_java' -or $java[0].java_app_class -ne $bundleManifest.java_app_class -or
        $java[0].toolkit -ne 'object' -or $java[0].creo_type -ne 'parametric' -or
        $java[0].java_app_start -ne 'start' -or $java[0].java_app_stop -ne 'stop') {
        throw 'Internal trial registry has an unknown application or Java entry point.'
    }
    $textDir = [string]$native[0].text_dir
    $textPath = if ([System.IO.Path]::IsPathFullyQualified($textDir)) { $textDir } else { Join-Path $installedPath $textDir }
    if (-not [string]::Equals([System.IO.Path]::GetFullPath($textPath), $installedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Internal trial registry text resources differ from the bound installation.'
    }
    foreach ($entry in @(@{ block = $native[0]; key = 'exec_file'; file = 'creo_cli_sketch.dll' },
        @{ block = $java[0]; key = 'java_app_classpath'; file = 'creo-cli-service.jar' })) {
        $value = [string]$entry.block[$entry.key]
        if ([string]::IsNullOrEmpty($value)) { throw 'Internal trial registry has an absent component path.' }
        $resolved = if ([System.IO.Path]::IsPathFullyQualified($value)) { $value } else { Join-Path $installedPath $value }
        if (-not [string]::Equals([System.IO.Path]::GetFullPath($resolved), (Join-Path $installedPath $entry.file), [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Internal trial registry points outside the bound component installation.'
        }
    }
    $nativeKeys = @('name', 'startup', 'exec_file', 'text_dir', 'allow_stop', 'fail_tol', 'delay_start')
    $javaKeys = @('name', 'startup', 'toolkit', 'creo_type', 'java_app_class', 'java_app_classpath', 'java_app_start', 'java_app_stop', 'allow_stop', 'fail_tol', 'delay_start')
    if (@($native[0].Keys | Where-Object { $_ -notin $nativeKeys }).Count -or
        @($java[0].Keys | Where-Object { $_ -notin $javaKeys }).Count) { throw 'Internal trial registry contains unreviewed fields.' }
}

function Require-InternalIsolation {
    foreach ($path in @($startupPath, $runtimePath)) { [void](Assert-RegularLocalPath $path -MayBeMissing) }
    $audit = [ordered]@{ configuration_roots = @(); configuration_files = @(); registries = @(); startup_extra_sources = @(); environment = @(); psf = $preflightRecord.internal_trial.psf; complete = $false }
    $preflightRecord.internal_isolation = $audit
    # The generated protk.dat/config.pro are pinned separately. Other known
    # startup registry/config files must remain absent across creation/dispatch.
    foreach ($name in @('creotk.dat', 'prodev.dat', 'config.sup')) {
        $candidate = Join-Path $startupPath $name
        $found = Test-Path -LiteralPath $candidate
        $audit.startup_extra_sources += @{ path = $candidate; exists = $found }
        if ($found) { throw 'An unreviewed additional startup registry or protected config appeared; no launch.' }
    }
    # These variables can inject unrelated Java code or select undeclared registry/config sources.
    foreach ($name in @('PROTKDAT', 'CREOTKDAT', 'PRODEVDAT', 'TOOLKIT_REGISTRY_FILE', 'PRO_JAVA_CLASSPATH', 'CLASSPATH', 'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        $audit.environment += @{ name = $name; configured = (-not [string]::IsNullOrEmpty($value)); disposition = 'must_be_absent' }
        if (-not [string]::IsNullOrEmpty($value)) { throw 'An inherited registry or Java injection variable prevents isolated internal startup.' }
    }
    foreach ($entry in @(@{ name = 'PRO_DIRECTORY'; expected = (Join-Path $launchCreoRoot 'Common Files') }, @{ name = 'PRO_MACHINE_TYPE'; expected = 'x86e_win64' })) {
        $value = [Environment]::GetEnvironmentVariable($entry.name)
        $audit.environment += @{ name = $entry.name; configured = (-not [string]::IsNullOrEmpty($value)); disposition = 'absent_or_declared_installation' }
        if (-not [string]::IsNullOrEmpty($value) -and -not [string]::Equals($value.TrimEnd('\', '/'), $entry.expected.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'An inherited Creo installation selector differs from this declared instance.'
        }
    }
    # PTC's three normal vendor launch commands are allowed; user RUN hooks and
    # environment assignments that inject Java, registries or config are refused.
    $allowedRuns = @('^RUN="%MECH_LP%\\install\\nt\\pro_mech_env\.bat"$', '^RUN="%PRO_DIRECTORY%\\%PRO_MACHINE_TYPE%\\nms\\nmsd\.exe" -noservice -timeout %NMSD_TIMEOUT% &$','^RUN="%PRO_DIRECTORY%\\%PRO_MACHINE_TYPE%\\obj\\xtop\.exe"$')
    $hasMechanismRun = $false; $hasStandardMechanismRoot = $false
    foreach ($line in [System.IO.File]::ReadAllLines($creoPsf)) {
        if ($line -match '^\s*RUN=') {
            if (-not @($allowedRuns | Where-Object { $line -match $_ }).Count) { throw 'An additional PSF RUN hook prevents isolated internal startup.' }
            if ($line -match '^RUN="%MECH_LP%') { $hasMechanismRun = $true }
        }
        if ($line -match '^\s*ENV=MECH_LP[+\-]?=') {
            if ($line -ne 'ENV=MECH_LP=%PRO_DIRECTORY%\applications\simulate') { throw 'The PSF redirects its standard vendor hook root.' }
            $hasStandardMechanismRoot = $true
        }
        if ($line -match '^\s*CREO_COMMON_FILES=' -and $line -ne 'CREO_COMMON_FILES=Common Files') { throw 'The PSF redirects its declared Creo Common Files root.' }
        if ($line -match '^\s*ENV=(?:PROTKDAT|CREOTKDAT|PRODEVDAT|TOOLKIT_REGISTRY_FILE|PRO_JAVA_COMMAND|PRO_JAVA_CLASSPATH|CLASSPATH|JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|JDK_JAVA_OPTIONS|PTC_CREO_ALT_SETTINGS_PATH|HOME|HOMEDRIVE|HOMEPATH|USERPROFILE)[+\-]?=') {
            throw 'A PSF environment override prevents isolated internal startup.'
        }
        if ($line -match '^\s*ENV=(?:PRO_DIRECTORY|PRO_MACHINE_TYPE|CREOAPP_DIRECTORY)[+\-]?=') { throw 'The PSF overrides a declared installation selector.' }
    }
    if ($hasMechanismRun -and -not $hasStandardMechanismRoot) { throw 'The PSF vendor hook depends on an unbound inherited MECH_LP.' }
    Require-ReviewedTrialRegistry
    foreach ($root in @(Get-InternalSourceRoots)) {
        [void](Assert-RegularLocalPath $root -MayBeMissing)
        $audit.configuration_roots += $root
        foreach ($name in @('creotk.dat', 'protk.dat', 'prodev.dat')) {
            $candidate = Join-Path $root $name
            $found = Test-Path -LiteralPath $candidate
            $record = [ordered]@{ path = $candidate; exists = $found; active_entries = $false }
            $audit.registries += $record
            if ($found) {
                $identity = Get-TrialFile $candidate
                $record.sha256 = $identity.sha256; $record.bytes = $identity.bytes
                $record.active_entries = @([System.IO.File]::ReadAllLines($candidate) | Where-Object { $_ -notmatch '^\s*(?:[!#].*)?$' }).Count -gt 0
                if ($record.active_entries) { throw 'An additional TOOLKIT registry contains applications; isolated internal startup is refused.' }
            }
        }
        foreach ($name in @('config.pro', 'config.sup')) {
            $candidate = Join-Path $root $name
            $found = Test-Path -LiteralPath $candidate
            $configRecord = [ordered]@{ path = $candidate; exists = $found }
            $audit.configuration_files += $configRecord
            if ($found) {
                $identity = Get-TrialFile $candidate
                $configRecord.sha256 = $identity.sha256; $configRecord.bytes = $identity.bytes
                foreach ($line in [System.IO.File]::ReadAllLines($candidate)) {
                    if ($line -match '^\s*(?:creotkdat|protkdat|prodevdat|toolkit_registry_file)(?:\s|=|$)') {
                        throw 'An external configuration declares additional TOOLKIT registries; isolated internal startup is refused.'
                    }
                }
            }
        }
    }
    $audit.complete = $true
    return $audit
}
