# Fresh per-process Creo recovery storage. No old recovery data is read, copied,
# removed or disabled; no window input or recovery action is performed.
function Assert-RecoveryLocalPath([string]$Path, [switch]$New) {
    $resolved = Resolve-OwnedPath $Path
    if ($New -and (Test-Path -LiteralPath $resolved)) { throw 'Recovery storage must be a new owned path; prior data is preserved.' }
    $cursor = $resolved
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $entry = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Recovery paths cannot cross links or reparse points.' }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $resolved
}

function Get-RecoveryConfigurationRoots {
    $roots = @((Join-Path $launchCreoRoot 'Common Files/text'), (Join-Path $launchCreoRoot 'Common Files/x86e_win64/text'))
    foreach ($base in @($roots)) {
        if (Test-Path -LiteralPath $base) {
            $roots += @(Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction Stop | ForEach-Object { $_.FullName })
        }
    }
    $roots += [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if ($loginConfigurationExplicit) { $roots += (Resolve-OwnedPath $LoginConfigurationDirectory) }
    if (-not [string]::IsNullOrEmpty($env:HOME)) { $roots += (Resolve-OwnedPath $env:HOME) }
    if (-not [string]::IsNullOrEmpty($env:HOMEDRIVE) -and -not [string]::IsNullOrEmpty($env:HOMEPATH)) {
        $roots += (Resolve-OwnedPath ($env:HOMEDRIVE + $env:HOMEPATH))
    }
    if (-not [string]::IsNullOrEmpty($env:PTC_CREO_ALT_SETTINGS_PATH)) { $roots += (Resolve-OwnedPath $env:PTC_CREO_ALT_SETTINGS_PATH) }
    return @($roots | Select-Object -Unique)
}

function Require-OwnedRecoveryDirectories([switch]$Empty) {
    foreach ($path in @($workflowRootPath, $lastSessionPath)) {
        [void](Assert-RecoveryLocalPath $path)
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'An owned recovery directory is absent or changed type.' }
        if ($Empty -and @(Get-ChildItem -LiteralPath $path -Force -ErrorAction Stop).Count -ne 0) {
            throw 'Recovery storage was populated before the owned process started; no old session can be imported.'
        }
    }
}

function Get-RecoveryDirectoryIdentity([string]$Value) {
    if ($Value.Contains('"') -or $Value -match '[\x00-\x1f]' -or -not [IO.Path]::IsPathFullyQualified($Value)) {
        throw 'Recovery directory identity requires an unquoted fully qualified path without control characters.'
    }
    return [IO.Path]::TrimEndingDirectorySeparator([IO.Path]::GetFullPath($Value))
}

function Get-OwnedRecoveryDirectoryValue {
    $value = [IO.Path]::GetRelativePath($startupPath, $lastSessionPath)
    if ([string]::IsNullOrEmpty($value) -or $value -eq '.' -or [IO.Path]::IsPathRooted($value) -or
        $value -match '[^\x21-\x7e]' -or $value -match '["!#:]') {
        throw 'Recovery config requires an unquoted ASCII relative path token under the common owned parent; cross-drive, whitespace, control and quote/comment syntax is unsupported.'
    }
    $resolved = [IO.Path]::GetFullPath((Join-Path $startupPath $value))
    if (-not [string]::Equals($resolved, $lastSessionPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Relative recovery configuration does not identify the exact owned directory.'
    }
    return $value
}

function Read-RecoveryIsolationSources {
    $sources = @(); $locked = @{}
    if ($lastSessionPath.Length -gt 259) { throw 'Owned recovery directory exceeds the supported native 260-character option bound.' }
    $configuredDirectory = Get-OwnedRecoveryDirectoryValue
    foreach ($variable in @('PTC_WF_CACHE', 'PTC_WLD_ROOT')) {
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($variable))) {
            throw 'An inherited alternate Creo cache selector prevents a new isolated recovery root.'
        }
    }
    foreach ($line in [System.IO.File]::ReadAllLines($creoPsf)) {
        if ($line -match '^\s*ENV=(?:PTC_WF_ROOT|PTC_WF_CACHE|PTC_WLD_ROOT)[+\-]?=') {
            throw 'The selected PSF overrides an owned recovery/cache root; no isolated launch.'
        }
    }
    foreach ($root in @(Get-RecoveryConfigurationRoots)) {
        [void](Assert-RecoveryLocalPath $root)
        foreach ($name in @('config.sup', 'config.pro')) {
            $path = Join-Path $root $name
            $entry = [ordered]@{ path = $path; protected = ($name -eq 'config.sup'); exists = (Test-Path -LiteralPath $path); selected_values = @{} }
            $sources += $entry
            if (-not $entry.exists) { continue }
            $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'A recovery configuration source is not a regular file.' }
            $before = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            foreach ($line in [System.IO.File]::ReadAllLines($path)) {
                if ($line -notmatch '^\s*(last_session_directory_path|last_session_retrieval)(?:\s|$)') { continue }
                if ($line -match '^\s*last_session_retrieval\s+(yes|no)\s*(?:[!#].*)?$') {
                    $entry.selected_values.last_session_retrieval = $Matches[1].ToLowerInvariant()
                } elseif ($line -match '^\s*last_session_directory_path\s+(?:"([^"]+)"|([^!#]+?))\s*(?:[!#].*)?$') {
                    $value = if ($Matches[1]) { $Matches[1] } else { $Matches[2].Trim() }
                    if ([string]::IsNullOrWhiteSpace($value)) { throw 'An empty recovery directory option prevents isolated startup.' }
                    $entry.selected_values.last_session_directory_path = $value
                } else { throw 'A recovery configuration option is malformed or unsupported.' }
            }
            $entry.sha256 = $before
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $before) { throw 'A recovery source changed during preflight.' }
            if ($entry.protected) {
                foreach ($key in $entry.selected_values.Keys) {
                    if ($locked.ContainsKey($key) -and $locked[$key] -ne $entry.selected_values[$key]) { throw 'Protected recovery settings conflict.' }
                    $locked[$key] = $entry.selected_values[$key]
                }
            }
        }
    }
    if ($locked.ContainsKey('last_session_retrieval') -and $locked.last_session_retrieval -ne 'yes') {
        throw 'Protected configuration disables recovery recording; it cannot be overridden.'
    }
    if ($locked.ContainsKey('last_session_directory_path')) {
        $value = $locked.last_session_directory_path
        if (-not [string]::Equals((Get-RecoveryDirectoryIdentity $value), (Get-RecoveryDirectoryIdentity $lastSessionPath), [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Protected recovery storage differs from the new owned directory; no override or launch.'
        }
    }
    return [ordered]@{
        workflow_root = $workflowRootPath; last_session_directory_path = $lastSessionPath
        configured_directory_value = $configuredDirectory
        recording = 'yes'; new_paths_before_launch = $true; configuration_sources = $sources
        inherited_workflow_root_replaced_in_child_only = (-not [string]::IsNullOrEmpty($env:PTC_WF_ROOT))
        previous_recovery_data_read_copied_removed = $false
        psf_sha256 = (Get-FileHash -LiteralPath $creoPsf -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Require-RecoveryReadback([object]$Response) {
    $actual = $Response.recovery_configuration
    if ($null -eq $actual -or $actual.complete -isnot [bool] -or $actual.complete -ne $true -or
        $actual.workflow_root -isnot [string] -or $actual.last_session_directory_path -isnot [string] -or
        $actual.last_session_retrieval -isnot [string] -or $actual.last_session_retrieval -ine 'yes' -or
        ($actual.last_session_directory_path_value_count -isnot [int] -and $actual.last_session_directory_path_value_count -isnot [long]) -or $actual.last_session_directory_path_value_count -ne 1 -or
        $actual.last_session_directory_path_readback -ne 'observed' -or $actual.last_session_retrieval_readback -ne 'observed' -or
        $actual.workflow_root_source -cne 'Java process environment inherited from owned Creo launcher' -or
        $actual.configuration_source -cne 'BaseSession.GetConfigOptionValues(last_session_directory_path)/GetConfigOption(last_session_retrieval)') {
        throw 'Native recovery isolation readback is absent or incomplete; no ready qualification.'
    }
    foreach ($pair in @(@{ observed = $actual.workflow_root; expected = $workflowRootPath }, @{ observed = $actual.last_session_directory_path; expected = $lastSessionPath })) {
        $value = $pair.observed
        if (-not [string]::Equals((Get-RecoveryDirectoryIdentity $value), (Get-RecoveryDirectoryIdentity $pair.expected), [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Actual recovery storage differs from this new owned runtime; no restore or fallback.'
        }
    }
    return $actual
}

function Get-OwnedRecoveryDialogs([int]$NativeProcessId) {
    if (-not ('CreoOwnedRecoveryWindows' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class CreoOwnedRecoveryWindows {
    public delegate bool Visitor(IntPtr window, IntPtr state);
    [DllImport("user32.dll", SetLastError=true)] static extern bool EnumWindows(Visitor callback, IntPtr state);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder text, int capacity);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
    public static string[] Find(uint expected) {
        var found=new List<string>();
        if (!EnumWindows((window,state)=> {
            uint process; GetWindowThreadProcessId(window,out process);
            if (process!=expected || !IsWindowVisible(window)) return true;
            var title=new StringBuilder(256); GetWindowText(window,title,256);
            string value=title.ToString();
            if (value=="Retrieval" || value=="检索" || value=="恢复") found.Add(value);
            return true;
        },IntPtr.Zero)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        return found.ToArray();
    }
}
'@
    }
    return @([CreoOwnedRecoveryWindows]::Find([uint32]$NativeProcessId))
}

function Require-NoOwnedRecoveryDialog([string]$Phase) {
    $nativeId = [int]$record.runtime_pin.native_pid
    [void](Owned-Process $nativeId $hostExecutable)
    $creation = [string](Get-Process -Id $nativeId -ErrorAction Stop).StartTime.ToUniversalTime().ToFileTimeUtc()
    if ($creation -ne [string]$record.runtime_pin.process_creations[[string]$nativeId]) { throw 'The owned native birth identity changed before recovery-window inspection.' }
    $titles = @(Get-OwnedRecoveryDialogs $nativeId)
    $record.recovery_window_observations += [ordered]@{
        phase = $Phase; native_pid = $nativeId; at_utc = [DateTime]::UtcNow.ToString('o')
        native_creation_filetime = $creation
        service_instance_id = $record.runtime_pin.service_instance_id
        component_source_sha256 = $bundleManifest.component_source_sha256
        source = 'OS EnumWindows/GetWindowThreadProcessId; only exact owned native PID; read-only'
        visible_windows_only = $true
        recovery_dialogs = $titles; desktop_input_count = 0; CUA_input_count = 0
    }
    if ($titles.Count -gt 0) {
        $record.external_blocker = [ordered]@{ code = 'owned_recovery_dialog_requires_input'; phase = $Phase; native_pid = $nativeId; action_performed = 'none'; recovery_data_preserved = $true }
        throw 'The owned Creo process has an unresolved recovery dialog; component readiness cannot qualify a new session.'
    }
}
