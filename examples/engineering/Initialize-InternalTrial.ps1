#requires -Version 7.4
param(
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$HistoryDirectory,
    [Parameter(Mandatory)][string]$CreoRoot,
    [Parameter(Mandatory)][string]$JavaHome,
    [ValidateRange(1024,65534)][int]$Port = 19616,
    [string]$PackageRoot = ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..')))
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Full([string]$Value) {
    if (-not [IO.Path]::IsPathFullyQualified($Value)) { throw 'Use an absolute local path.' }
    $path = [IO.Path]::GetFullPath($Value).TrimEnd('\','/')
    if ($path -eq [IO.Path]::GetPathRoot($path).TrimEnd('\','/')) { throw 'A filesystem root cannot be a trial workspace.' }
    $cursor = $path
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Use paths without symbolic links or junctions.' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $path
}
$work = Full $WorkRoot
$package = Full $PackageRoot
$history = Full $HistoryDirectory
$creo = Full $CreoRoot
$java = Full $JavaHome
$workspace = $work
while (-not ($package.Equals($workspace,[StringComparison]::OrdinalIgnoreCase) -or $package.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase))) {
    $workspace = [IO.Path]::GetDirectoryName($workspace)
    if (-not $workspace -or $workspace -eq [IO.Path]::GetPathRoot($workspace)) { throw 'Place the package and trial run beneath one dedicated workspace directory.' }
}
$staging = Full (Join-Path $workspace '.creo-cli/staging')
if (-not [IO.Directory]::Exists($history)) { throw 'Declare an existing continuing CLI history directory. For a first installation, explicitly create an empty history directory first.' }
if ([IO.Directory]::Exists((Join-Path $work 'installation')) -or (Test-Path -LiteralPath (Join-Path $work 'environment.json'))) { throw 'This workspace has an installation or environment; preserve it and choose a new trial workspace.' }
$manifest = Get-Content -LiteralPath (Join-Path $package 'PACKAGE-MANIFEST.json') -Raw | ConvertFrom-Json -AsHashtable
foreach ($name in $manifest.files.Keys) {
    if ($name -match '(^|/)\.\.(/|$)' -or [IO.Path]::IsPathRooted($name)) { throw 'Unsafe manifest path.' }
    $file = Full (Join-Path $package $name)
    if (-not $file.StartsWith($package + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path leaves package.' }
    $expected = $manifest.files[$name]
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected.sha256 -or (Get-Item -LiteralPath $file).Length -ne $expected.bytes) { throw "Package integrity mismatch: $name" }
}
foreach ($file in @((Join-Path $creo 'Parametric/bin/parametric.exe'),(Join-Path $java 'bin/java.exe'))) { if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing declared dependency: $file" } }
New-Item -ItemType Directory -Path $work -Force | Out-Null
foreach ($directory in @('evidence','projects','requests','images')) { New-Item -ItemType Directory -Path (Join-Path $work $directory) | Out-Null }
$scope = [ordered]@{scope_id=('creo-internal-' + [guid]::NewGuid().ToString('N'));tool='creo-cli';granted_by='Explicit user invocation of Initialize-InternalTrial.ps1 for this isolated workspace';granted_at=[DateTime]::UtcNow.ToString('o');expires_at=$null;effects=@('observe','session','change','persist','artifact');dangerous=$true;roots=@($work,$package,$staging);outputs=@($work,$staging);limits=@{max_operations=1000};notes='Isolated copied projects and exact workspace/.creo-cli/staging only. Preserve history, unknown results and all other application sessions.'}
$scopePath = Join-Path $work 'scope.json'
$scope | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $scopePath -Encoding utf8
$environment = [ordered]@{CREO_CLI_WORKSPACE=$workspace;CREO_CLI_CONFIG_DIR=$history;CREO_CLI_PERMISSION='write';CREO_CLI_EXPERIMENTAL_NATIVE_WRITES='1';CREO_CLI_SCOPE_FILE=$scopePath;CREO_CLI_SERVICE_URL="http://127.0.0.1:$Port";CREO_CLI_SERVICE_TOKEN_FILE=(Join-Path $work 'runtime-1/service-token')}
Get-ChildItem Env:CREO_CLI_* | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
foreach ($key in $environment.Keys) { [Environment]::SetEnvironmentVariable($key,[string]$environment[$key],'Process') }
$exe = Join-Path $package 'cli/creo-cli.exe'
$install = Join-Path $work 'installation'
$previewText = & $exe service install --from (Join-Path $package 'cli/service-bundle') --target $install --dry-run --json --compact --timeout 300
$previewText | Set-Content -LiteralPath (Join-Path $work 'evidence/install-preview.json') -Encoding utf8
$preview = $previewText | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $preview.ok) { throw 'Service installation preview refused; original receipt retained.' }
$resultText = & $exe service install --from (Join-Path $package 'cli/service-bundle') --target $install --confirm $preview.data.confirm_token --json --compact --timeout 300
$resultText | Set-Content -LiteralPath (Join-Path $work 'evidence/install-confirm.json') -Encoding utf8
$result = $resultText | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $result.ok) { throw 'Service installation failed; preserve this workspace and inspect the retained receipt.' }
$declaration = [ordered]@{schema_version='1.0';package=$package;creo=$creo;java=$java;installation=$install;base_port=$Port;environment_variables=$environment}
$declaration | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $work 'environment.json') -Encoding utf8
Write-Output "Prepared isolated component installation: $work"
Write-Output 'Copy your own authorized project and dependencies into projects before opening a model.'
Write-Output 'No Creo or Java process was started. Read README, then use Start-CreoWorkspace.ps1.'
