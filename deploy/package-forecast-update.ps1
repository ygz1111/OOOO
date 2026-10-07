$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputParent = Join-Path $projectRoot '.codex_tmp'
$stageRoot = Join-Path $outputParent ('forecast-update-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
$backendFiles = @('tf_realtime_feature_provider.py', 'tf_split_service.py',
    'services/live_forecast.py', 'services/prediction_pipeline.py', 'services/prediction_insight.py',
    'routers/prediction.py', 'routers/price.py', 'routers/generation.py', 'schemas/core.py')
foreach ($file in $backendFiles) {
    $relative = 'backend/realtime_api/' + $file
    $target = Join-Path $stageRoot $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot $relative) -Destination $target
}
New-Item -ItemType Directory -Path (Join-Path $stageRoot 'frontend') | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'frontend/dist') -Destination (Join-Path $stageRoot 'frontend/dist') -Recurse
foreach ($name in @('Dockerfile.forecast-update', 'apply-forecast-update.sh', 'UPDATE-FORECAST.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $stageRoot $name)
}
$files = @(Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force)
if ($files.Name -contains '.env' -or $files.Name -contains 'docker-compose.server.yml' -or $files.Name -contains 'requirements-server.txt') { throw 'Forbidden deployment config in update' }
$manifest = $files | Sort-Object FullName | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(), ([IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace('\', '/'))
}
[IO.File]::WriteAllText((Join-Path $stageRoot 'SHA256SUMS'), (($manifest -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
$archive = Join-Path $outputParent 'smartgrid-forecast-update.zip'
if (Test-Path -LiteralPath $archive) { throw 'Archive already exists; preserve it and choose a new output name before rebuilding.' }
$stream = [IO.File]::Open($archive, [IO.FileMode]::CreateNew)
try {
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $false, [Text.Encoding]::UTF8)
    try {
        Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force | ForEach-Object {
            $entry = 'smartgrid-forecast-update/' + [IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace('\', '/')
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $entry) | Out-Null
        }
    } finally { $zip.Dispose() }
} finally { $stream.Dispose() }
Write-Output "Archive: $archive"
Write-Output ('Size: {0:N2} MB' -f ((Get-Item -LiteralPath $archive).Length / 1MB))
