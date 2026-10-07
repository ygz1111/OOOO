param(
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputParent = Join-Path $projectRoot '.codex_tmp'
$stageBase = Join-Path $outputParent ('server-upload-' + [guid]::NewGuid().ToString('N'))
$stageRoot = Join-Path $stageBase 'smartgrid-server'
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

function Get-BundleRelativePath([string]$FullPath) {
    # Windows PowerShell 5.1 has no Path.GetRelativePath.
    $rootUri = [Uri]::new($projectRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar)
    $fileUri = [Uri]::new($FullPath)
    return [Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString()).Replace('/', [IO.Path]::DirectorySeparatorChar)
}

function Copy-BundleFile([string]$RelativePath) {
    $sourcePath = Join-Path $projectRoot $RelativePath
    $targetPath = Join-Path $stageRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Missing: $RelativePath" }
    New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath
}

foreach ($folder in @('backend/realtime_api', 'backend/models/tensorflow_load')) {
    Get-ChildItem -LiteralPath (Join-Path $projectRoot $folder) -Recurse -File -Filter '*.py' |
        ForEach-Object { Copy-BundleFile (Get-BundleRelativePath $_.FullName) }
}
foreach ($folder in @('backend/config', 'backend/models/tf_assets', 'frontend/dist', 'deploy')) {
    Get-ChildItem -LiteralPath (Join-Path $projectRoot $folder) -Recurse -File -Force |
        Where-Object { $_.FullName -notmatch '[/\\]__pycache__[/\\]' } |
        ForEach-Object { Copy-BundleFile (Get-BundleRelativePath $_.FullName) }
}
foreach ($relativePath in @('processed/step4_feature_config.pkl', 'processed/step5_scalers.pkl', 'processed/step5_split_info.pkl')) {
    Copy-BundleFile $relativePath
}

# Generate a fresh-server schema from the existing schema without sample weather rows.
# The source file stays unchanged; the new database must contain real observations only.
$sqlSource = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'docker/init-db.sql') -Encoding UTF8
$samplePattern = '(?s)-- \u63d2\u5165\u793a\u4f8b\u6c14\u8c61\u6570\u636e\r?\nINSERT INTO weather_data .*?;'
if ([regex]::Matches($sqlSource, $samplePattern).Count -ne 1) { throw 'Unexpected sample-data SQL layout.' }
$sqlBundle = [regex]::Replace($sqlSource, $samplePattern, '-- No sample observations in the server database.')
New-Item -ItemType Directory -Path (Join-Path $stageRoot 'docker') | Out-Null
[IO.File]::WriteAllText((Join-Path $stageRoot 'docker/init-db.sql'), $sqlBundle, [Text.UTF8Encoding]::new($false))

$files = @(Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force)
if ($files.Name -contains '.env' -or $files.FullName -match '[/\\](node_modules|__pycache__|logs)[/\\]') {
    throw 'Forbidden local/runtime files found in bundle.'
}
$requiredPaths = @('frontend/dist/index.html', 'backend/models/tf_assets/tf_split_v1/load_best.weights.h5',
    'backend/models/tf_assets/tf_split_v1/price_best.weights.h5', 'backend/models/tf_assets/pv_v2/pv_v2_best.weights.h5')
foreach ($requiredPath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot $requiredPath))) { throw "Missing: $requiredPath" }
}
$manifest = $files | Sort-Object FullName | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(),
        ([Uri]::UnescapeDataString(([Uri]::new($stageRoot + [IO.Path]::DirectorySeparatorChar)).MakeRelativeUri([Uri]::new($_.FullName)).ToString()))
}
[IO.File]::WriteAllText((Join-Path $stageRoot 'SHA256SUMS'), (($manifest -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
$archive = if ($OutputPath) { [IO.Path]::GetFullPath($OutputPath) } else { Join-Path $outputParent 'smartgrid-server-upload.zip' }
New-Item -ItemType Directory -Path (Split-Path -Parent $archive) -Force | Out-Null
$zipStream = [IO.File]::Open($archive, [IO.FileMode]::Create)
try {
    $zipWriter = [IO.Compression.ZipArchive]::new($zipStream, [IO.Compression.ZipArchiveMode]::Create, $false, [Text.Encoding]::UTF8)
    try {
        Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force | ForEach-Object {
            $entryName = 'smartgrid-server/' + [Uri]::UnescapeDataString(([Uri]::new($stageRoot + [IO.Path]::DirectorySeparatorChar)).MakeRelativeUri([Uri]::new($_.FullName)).ToString())
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zipWriter, $_.FullName, $entryName) | Out-Null
        }
    } finally { $zipWriter.Dispose() }
} finally { $zipStream.Dispose() }
Write-Output "Stage: $stageRoot"
Write-Output "Archive: $archive"
Write-Output ('Size: {0:N2} MB' -f ((Get-Item -LiteralPath $archive).Length / 1MB))
