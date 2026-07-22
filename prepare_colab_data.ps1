# ========================================
# 准备 Colab 训练数据 - 快速脚本
# ========================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "准备 Google Colab 训练数据" -ForegroundColor Cyan
Write-Host "========================================`n"

# 1. 压缩 processed 目录
Write-Host "[1/2] 压缩 processed 目录..." -ForegroundColor Yellow
Compress-Archive -Path ".\processed" -DestinationPath ".\processed.zip" -Force
Write-Host "✓ processed.zip 已创建`n" -ForegroundColor Green

# 2. 压缩 models 目录
Write-Host "[2/2] 压缩 models 目录..." -ForegroundColor Yellow
Compress-Archive -Path ".\models" -DestinationPath ".\models.zip" -Force
Write-Host "✓ models.zip 已创建`n" -ForegroundColor Green

# 3. 显示文件大小
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "文件信息" -ForegroundColor Cyan
Write-Host "========================================`n"

Get-ChildItem -Filter "*.zip" | ForEach-Object {
    $size = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  $($_.Name): $size MB" -ForegroundColor White
}

# 4. 下一步提示
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "下一步操作" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Yellow
Write-Host "1. 打开 docs/Colab训练指南.md" -ForegroundColor White
Write-Host "2. 将 processed.zip 和 models.zip 上传到 Google Drive" -ForegroundColor White
Write-Host "3. 按照 Colab 训练指南在 Google Colab 中运行训练`n"

Write-Host "是否打开 Colab 训练指南? (Y/N): " -ForegroundColor Green -NoNewline
$response = Read-Host

if ($response -eq 'Y' -or $response -eq 'y') {
    Start-Process "docs\Colab训练指南.md"
}

Write-Host "`n准备完成！" -ForegroundColor Green
Write-Host "预计训练时间: 2-4 小时（使用 T4 GPU）`n"