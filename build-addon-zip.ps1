# Kodi-Installations-ZIP: Pfade immer mit Schrägstrichen, Wurzel = plugin.video.massengeschmack/
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $root 'plugin.video.massengeschmack'
$version = ([xml](Get-Content (Join-Path $source 'addon.xml'))).addon.version
$zipPath = Join-Path $root "plugin.video.massengeschmack-$version.zip"

if (-not (Test-Path $source)) {
    throw "Addon-Ordner fehlt: $source"
}
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
$prefix = $root.TrimEnd('\') + '\'
Get-ChildItem $source -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($prefix.Length) -replace '\\', '/'
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip, $_.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal)
}
$zip.Dispose()

$check = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
$bad = $check.Entries | Where-Object { $_.FullName -match '\\' -or $_.FullName -notmatch '^plugin\.video\.massengeschmack/' }
$check.Dispose()
if ($bad) { throw "Ungültige ZIP-Einträge: $($bad.Count)" }

$share = '\\mainserver\PublicDrive\XBMC'
Copy-Item -Path $zipPath -Destination (Join-Path $share (Split-Path $zipPath -Leaf)) -Force
$unpack = Join-Path $share 'kopieren-nach-kodi-addons\plugin.video.massengeschmack'
if (-not (Test-Path $unpack)) {
    New-Item -ItemType Directory -Path $unpack -Force | Out-Null
}
Copy-Item -Path (Join-Path $source '*') -Destination $unpack -Recurse -Force
Write-Output "OK $zipPath $((Get-Item $zipPath).Length) bytes, Version $version"
Write-Output "Share: $(Join-Path $share (Split-Path $zipPath -Leaf))"