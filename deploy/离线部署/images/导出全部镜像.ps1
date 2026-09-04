#requires -Version 5.1
# 一键导出全部 KB 基础设施镜像为 .tar.gz
# 用法：把此文件放在 images\ 目录下，PowerShell 中执行 .\导出全部镜像.ps1
#       或在文件资源管理器中右键"使用 PowerShell 运行"

$ErrorActionPreference = "Stop"
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

foreach ($img in $images) {
    Write-Host "==> 导出 $($img.src) ..." -ForegroundColor Cyan
    docker save $img.src | gzip > $img.file
    $size = (Get-Item $img.file).Length / 1GB
    Write-Host "    完成: $($img.file)  ($([math]::Round($size, 2)) GB)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "==> 全部完成。文件清单:" -ForegroundColor Green
Get-ChildItem *.tar.gz | Format-Table Name, @{n="GB";e={[math]::Round($_.Length/1GB, 2)}} -AutoSize

Write-Host ""
Write-Host "下一步：把 images\ 整个目录拷到 U 盘/移动硬盘/内网共享目录。" -ForegroundColor Yellow
Write-Host "在内网机器上运行 加载全部镜像.sh（或 gunzip -c xxx.tar.gz | docker load）。" -ForegroundColor Yellow