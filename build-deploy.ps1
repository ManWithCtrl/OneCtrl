# 打包部署包 deploy-package.zip（Windows PowerShell）
# 用法：  powershell -ExecutionPolicy Bypass -File build-deploy.ps1
# 产物：  deploy-package.zip（上传到服务器 ~/ 后跑 bash ~/deploy/update.sh）
#
# 注意：不要用 ZipFile::CreateFromDirectory —— .NET Framework 版本会把目录分隔符写成
# 反斜杠（static\app.js），Linux 上解压会得到一个名字带反斜杠的文件而不是目录。
# 这里手动逐条 CreateEntry，条目名统一用正斜杠。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$out  = Join-Path $root 'deploy-package.zip'
if (Test-Path $out) { Remove-Item $out -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$files = @()
$files += Get-ChildItem (Join-Path $root 'ctrl_*.py') -File
$files += Get-Item (Join-Path $root 'templates\index.html')
$files += Get-ChildItem (Join-Path $root 'static\*') -File
$files += Get-ChildItem (Join-Path $root 'deploy\*') -File

$zip = [System.IO.Compression.ZipFile]::Open($out, 'Create')
foreach ($f in $files) {
    $rel = $f.FullName.Substring($root.Length + 1) -replace '\\', '/'
    $e = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $s = $e.Open()
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $s.Write($bytes, 0, $bytes.Length)
    $s.Dispose()
}
$zip.Dispose()

$z = [System.IO.Compression.ZipFile]::OpenRead($out)
$n = $z.Entries.Count
$bad = 0
foreach ($e in $z.Entries) {
    if ($e.FullName.Contains('\')) { $bad++; Write-Output ("BAD SEPARATOR: " + $e.FullName) }
}
$b = (Get-Item $out).Length
$z.Dispose()
Write-Output ("deploy-package.zip: {0} files, {1} bytes, bad-sep={2}" -f $n, $b, $bad)
