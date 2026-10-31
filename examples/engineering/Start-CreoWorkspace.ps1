#requires -Version 7.4
param([Parameter(Mandatory)][string]$WorkRoot,[ValidateRange(1,2)][int]$Sequence=1,[switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start-InternalTrial.ps1') @PSBoundParameters
