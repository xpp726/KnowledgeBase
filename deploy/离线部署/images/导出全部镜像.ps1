#requires -Version 5.1
# 一键导出全部 KB 基础设施镜像为 .tar.gz
# 用法：把此文件放在 images\ 目录下，PowerShell 中执行 .\导出全部镜像.ps1
#       或在文件资源管理器中右键"使用 PowerShell 运行"

# 终端中文显示修复（避免 PowerShell 默认 GBK 编码把 UTF-8 中文读成乱码）
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding          = [System.Text.Encoding]::UTF8

# 单个镜像失败不阻塞其他镜像继续导出
$ErrorActionPreference = "Continue"

$outDir = $PSScriptRoot
if (-not $outDir) { $outDir = (Get-Location).Path }
Set-Location $outDir

Write-Host "==> 输出目录: $outDir" -ForegroundColor Cyan
Write-Host ""

$images = @(
    @{ name = "kb-bge-m3";  src = "kb-bge-m3:latest";                                 file = "kb-bge-m3.tar.gz" },
    @{ name = "milvus";     src = "milvusdb/milvus:v2.5.27";                          file = "milvus.tar.gz" },
    @{ name = "etcd";       src = "quay.io/coreos/etcd:v3.5.5";                       file = "etcd.tar.gz" },
    @{ name = "minio";      src = "minio/minio:RELEASE.2023-12-20T01-00-02Z";         file = "minio.tar.gz" },
    @{ name = "attu";       src = "zilliz/attu:v2.5";                                 file = "attu.tar.gz" }
)

# 带重试的删除函数：Windows 上 docker save 完成后 .tar 句柄偶尔未释放
function Remove-ItemWithRetry {
    param([string]$Path, [int]$MaxAttempts = 6, [int]$DelaySeconds = 2)
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            if (Test-Path $Path) { Remove-Item $Path -Force -ErrorAction Stop }
            return $true
        } catch {
            if ($i -eq $MaxAttempts) {
                Write-Host "    [警告] 删除失败 $Path（共尝试 $MaxAttempts 次）: $($_.Exception.Message)" -ForegroundColor Yellow
                return $false
            }
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

foreach ($img in $images) {
    $gzPath  = Join-Path $outDir $img.file
    $tarPath = Join-Path $outDir ($img.file -replace '\.gz$', '')

    # 已存在 .tar.gz 且没有残留 .tar，跳过（避免重复压缩几 GB）
    if ((Test-Path $gzPath) -and -not (Test-Path $tarPath)) {
        $existSize = (Get-Item $gzPath).Length / 1GB
        Write-Host "==> $($img.src) 已存在 .tar.gz，跳过  ($([math]::Round($existSize, 2)) GB)" -ForegroundColor DarkGray
        Write-Host ""
        continue
    }

    # 清理上一次失败的残留 .tar
    if (Test-Path $tarPath) { Remove-ItemWithRetry -Path $tarPath | Out-Null }

    Write-Host "==> 导出 $($img.src) ..." -ForegroundColor Cyan

    # 1) docker save 写到临时 .tar
    $saveOk = $false
    try {
        docker save -o $tarPath $img.src
        $saveOk = $true
    } catch {
        Write-Host "    [错误] docker save 失败: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        continue
    }
    if (-not $saveOk) { continue }

    # 2) 用 .NET GZipStream 压缩成 .tar.gz（与 Linux gzip 字节级兼容）
    try {
        $src = [System.IO.File]::OpenRead($tarPath)
        $dst = [System.IO.File]::Create($gzPath)
        $gz  = New-Object System.IO.Compression.GZipStream($dst, [System.IO.Compression.CompressionMode]::Compress)
        try {
            $src.CopyTo($gz)
        } finally {
            $gz.Dispose()
            $dst.Dispose()
            $src.Dispose()
        }
    } catch {
        Write-Host "    [错误] gzip 压缩失败: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        continue
    }

    # 3) 删 .tar，只留 .tar.gz（带重试）
    $removed = Remove-ItemWithRetry -Path $tarPath

    $size = (Get-Item $gzPath).Length / 1GB
    $status = if ($removed) { "完成" } else { "完成（.tar 未清理，需手动删除）" }
    Write-Host "    $status : $($img.file)  ($([math]::Round($size, 2)) GB)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "==> 全部完成。文件清单:" -ForegroundColor Green
Get-ChildItem *.tar.gz -ErrorAction SilentlyContinue | Format-Table Name, @{n="GB";e={[math]::Round($_.Length/1GB, 2)}} -AutoSize

Write-Host ""
Write-Host "下一步：把 images\ 整个目录拷到 U 盘/移动硬盘/内网共享目录。" -ForegroundColor Yellow
Write-Host "在内网机器上运行 加载全部镜像.sh（或 gunzip -c xxx.tar.gz | docker load）。" -ForegroundColor Yellow