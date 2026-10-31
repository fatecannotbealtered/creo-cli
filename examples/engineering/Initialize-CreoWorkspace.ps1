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
& (Join-Path $PSScriptRoot 'Initialize-InternalTrial.ps1') @PSBoundParameters
