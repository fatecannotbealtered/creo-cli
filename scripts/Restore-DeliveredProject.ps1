#requires -Version 7.4
<#
.SYNOPSIS
Restore one manifest-bound, flat Creo project archive into an empty owned directory.
.DESCRIPTION
This is a file helper, not a Creo or CLI command. Supply the archive SHA-256 from
the already verified delivery manifest and the expected entry from its instructions.
It creates no directories and does not remove partial files after a failure.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ArchivePath,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [Parameter(Mandatory)][string]$ExpectedEntry,
    [Parameter(Mandatory)][string]$OwnedRoot,
    [Parameter(Mandatory)][string]$TargetDirectory,
    [Parameter(Mandatory)][string]$EvidencePath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function LocalPath([string]$Value) {
    if (-not [IO.Path]::IsPathFullyQualified($Value) -or $Value.StartsWith('\\') -or $Value.StartsWith('//')) {
        throw 'An absolute local path is required.'
    }
    $full = [IO.Path]::GetFullPath($Value).TrimEnd('\')
    if ($full.Length -le 2) { throw 'A drive root is not an allowed task path.' }
    return $full
}
function Within([string]$Value, [string]$Root) {
    return $Value.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)
}
function RefuseLinks([string]$Value) {
    $cursor = $Value
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'Links and reparse points are not allowed.'
        }
        $next = [IO.Path]::GetDirectoryName($cursor)
        if ($next -eq $cursor) { break }
        $cursor = $next
    }
}
function CheckLeaf([string]$Name) {
    if (-not $Name -or $Name -in @('.', '..') -or $Name -match '[/\\:]|[. ]$|[<>"|?*\x00-\x1f]' -or
        $Name -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
        throw 'This helper accepts only safe, flat archive member names.'
    }
}

$archive = LocalPath $ArchivePath
$root = LocalPath $OwnedRoot
$target = LocalPath $TargetDirectory
$evidence = LocalPath $EvidencePath
if ($ExpectedSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Expected SHA-256 must be 64 lowercase hexadecimal characters.' }
CheckLeaf $ExpectedEntry
if (-not (Within $target $root) -or -not (Within $evidence $root) -or
    $evidence -ieq $target -or (Within $evidence $target) -or (Within $archive $target)) {
    throw 'Target and evidence must be separate paths inside the owned root.'
}
foreach ($path in @($root, $archive, $target, $evidence)) { RefuseLinks $path }
if (-not (Test-Path -LiteralPath $root -PathType Container) -or
    -not (Test-Path -LiteralPath $target -PathType Container) -or
    @(Get-ChildItem -LiteralPath $target -Force).Count -ne 0 -or
    -not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($evidence)) -PathType Container) -or
    (Test-Path -LiteralPath $evidence)) {
    throw 'Use an existing empty target and a new evidence file under the owned root.'
}

$stream = [IO.FileStream]::new($archive, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    $before = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant()
    if ($before -cne $ExpectedSha256) { throw 'Archive SHA-256 mismatch.' }
    $stream.Position = 0
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read, $true)
    try {
        $entries = @($zip.Entries)
        $folded = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $totalBytes = 0L
        foreach ($item in $entries) {
            CheckLeaf $item.FullName
            if (-not $folded.Add($item.FullName)) { throw 'Duplicate or case-colliding ZIP member.' }
            if ((($item.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'ZIP link refused.' }
            if ($item.Length -gt 256MB) { throw 'ZIP member is too large.' }
            $totalBytes += $item.Length
            if ($totalBytes -gt 1GB) { throw 'ZIP contents are too large.' }
        }
        $manifestEntries = @($entries | Where-Object { $_.FullName -cin @('MODEL-MANIFEST.json', 'MANIFEST.json') })
        if ($manifestEntries.Count -ne 1) { throw 'Exactly one root project manifest is required.' }
        $reader = [IO.StreamReader]::new($manifestEntries[0].Open(), [Text.UTF8Encoding]::new($false, $true))
        try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json -AsHashtable -Depth 40 } finally { $reader.Dispose() }
        if ($manifest.entry -cne $ExpectedEntry -or $manifest.files -isnot [Collections.IDictionary]) {
            throw 'Manifest entry or file map does not match the expected project.'
        }
        $declared = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($name in $manifest.files.Keys) {
            CheckLeaf $name
            if (-not $declared.Add($name)) { throw 'Duplicate manifest member.' }
            $itemBinding = $manifest.files[$name]
            if ($itemBinding.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $itemBinding.bytes -isnot [ValueType] -or $itemBinding.bytes -lt 0) {
                throw 'Invalid member digest or size in manifest.'
            }
        }
        $actual = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $native = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($item in $entries) {
            $name = $item.FullName
            if ($name -ceq $manifestEntries[0].FullName) { continue }
            [void]$actual.Add($name)
            if (-not $manifest.files.Contains($name) -or $item.Length -ne $manifest.files[$name].bytes) {
                throw 'ZIP member is absent from the manifest or has a different size.'
            }
            if ($name -match '(?i)\.(prt|asm|drw)\.[1-9][0-9]*$') { [void]$native.Add($name) }
        }
        $listedNative = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($name in @($manifest.native_models)) {
            CheckLeaf $name
            if (-not $listedNative.Add($name)) { throw 'Duplicate native model declaration.' }
        }
        if (-not $actual.SetEquals($declared) -or -not $native.SetEquals($listedNative) -or -not $native.Contains($ExpectedEntry)) {
            throw 'Manifest members, native model inventory or entry differ from the archive.'
        }
        foreach ($item in $entries) {
            $destination = Join-Path $target $item.FullName
            RefuseLinks $destination
            $sourceStream = $item.Open()
            $outputStream = [IO.FileStream]::new($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            try { $sourceStream.CopyTo($outputStream); $outputStream.Flush($true) }
            finally { $sourceStream.Dispose(); $outputStream.Dispose() }
        }
        foreach ($name in $manifest.files.Keys) {
            $path = Join-Path $target $name
            RefuseLinks $path
            $item = Get-Item -LiteralPath $path
            if ($item.Length -ne $manifest.files[$name].bytes -or
                (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.files[$name].sha256) {
                throw 'Restored member digest or size mismatch; retain the partial directory.'
            }
        }
    } finally { $zip.Dispose() }
    $stream.Position = 0
    $after = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant()
    RefuseLinks $archive
    $pathHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($after -cne $ExpectedSha256 -or $pathHash -cne $ExpectedSha256) { throw 'Archive changed during restoration.' }
    $record = [ordered]@{
        schema = 'creo.delivered-project-restore.v1'; at_utc = [DateTime]::UtcNow.ToString('o')
        archive = $archive; archive_sha256 = $ExpectedSha256; owned_root = $root; destination = $target
        entry = $ExpectedEntry; native_models = @($manifest.native_models); verified_files = $manifest.files.Count
        archive_members = $entries.Count; file_only = $true; cad_calls = 0
        qualification = 'File restoration only; no native reopen or persistence claim.'
    }
    RefuseLinks $evidence
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json -Depth 10) + "`n")
    $receipt = [IO.FileStream]::new($evidence, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $receipt.Write($bytes, 0, $bytes.Length); $receipt.Flush($true) } finally { $receipt.Dispose() }
    $record | ConvertTo-Json -Depth 10 -Compress
} finally { $stream.Dispose() }
