#requires -Version 7.4
param([Parameter(Mandatory)][string]$WorkRoot,[ValidateRange(1,2)][int]$Sequence=1,[switch]$PreflightOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$work=[IO.Path]::GetFullPath($WorkRoot)
$environmentPath=Join-Path $work 'environment.json'
$declaration=Get-Content -LiteralPath $environmentPath -Raw|ConvertFrom-Json -AsHashtable
$package=$declaration.package
$build=Get-Content -LiteralPath (Join-Path $package 'BUILD-BINDING.json') -Raw|ConvertFrom-Json
function Bind([string]$Path) { $f=Get-Item -LiteralPath $Path; return [ordered]@{path=$f.FullName;sha256=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant();bytes=$f.Length} }
$manifest=Get-Content -LiteralPath (Join-Path $declaration.installation 'manifest.json') -Raw|ConvertFrom-Json
$preparationPath=Join-Path $package 'cli/deployment/native-preparation.json'
$preparation=Get-Content -LiteralPath $preparationPath -Raw|ConvertFrom-Json
$bindingPath=Join-Path $work "internal-trial-binding-$Sequence.json"
$files=[ordered]@{'creo-cli.exe'=(Bind (Join-Path $package 'cli/creo-cli.exe'))}
foreach($name in @('creo-cli-service.jar','creo_cli_sketch.dll')){$files[$name]=Bind (Join-Path $declaration.installation $name)}
$binding=[ordered]@{schema_version='1.0';mode='internal-unsigned-trial';source_commit=$build.component_source_commit;policy_profile='creo-13.4.1.0-unsigned-native';configuration_catalog=(Bind (Join-Path $declaration.creo 'Common Files/help/reference/pma/usascii/configoptions.pdf'));component_source_sha256=$manifest.component_source_sha256;native_source_fingerprint=$preparation.source_fingerprint;files=$files;registry=(Bind (Join-Path $declaration.installation 'protk.dat'));psf=(Bind (Join-Path $declaration.creo 'Parametric/bin/parametric.psf'));native_preparation=(Bind $preparationPath)}
$bindingText=$binding|ConvertTo-Json -Depth 16
if(Test-Path -LiteralPath $bindingPath){if((Get-Content -LiteralPath $bindingPath -Raw).Trim() -ne $bindingText.Trim()){throw 'Existing binding differs; preserve it and stop.'}}else{$bindingText|Set-Content -LiteralPath $bindingPath -Encoding utf8}
$runtime=Join-Path $work "runtime-$Sequence"
$startup=Join-Path $work "startup-$Sequence"
$port=[int]$declaration.base_port+$Sequence-1
Get-ChildItem Env:CREO_CLI_*|ForEach-Object{Remove-Item -LiteralPath ('Env:'+$_.Name)}
$variables=$declaration.environment_variables
$variables.CREO_CLI_SERVICE_TOKEN_FILE=Join-Path $runtime 'service-token'
$variables.CREO_CLI_SERVICE_URL="http://127.0.0.1:$port"
foreach($key in $variables.Keys){[Environment]::SetEnvironmentVariable($key,[string]$variables[$key],'Process')}
$parameters=@{CreoRoot=$declaration.creo;JavaHome=$declaration.java;InstallationDirectory=$declaration.installation;StartupDirectory=$startup;RuntimeDirectory=$runtime;Port=$port;WaitSeconds=180;TrustPolicy='internal-unsigned-trial';InternalTrialBinding=$bindingPath;ExpectedInternalTrialBindingSha256=(Bind $bindingPath).sha256}
if($PreflightOnly){$parameters.PreflightOnly=$true}
& (Join-Path $PSScriptRoot 'start-owned-creo.ps1') @parameters
if(-not $PreflightOnly){$declaration.environment_variables=$variables;$declaration|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $environmentPath -Encoding utf8}
