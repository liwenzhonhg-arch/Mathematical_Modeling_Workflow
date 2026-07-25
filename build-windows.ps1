param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Push-Location $root
try {
    $version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw "无法读取项目版本"
    }

    $releaseName = "MMW-Windows-x64-v$version"
    $workPath = Join-Path $root "build\pyinstaller-v$version"
    $distPath = Join-Path $root "dist\pyinstaller-v$version"
    $bundlePath = Join-Path $distPath "MMW"
    $archivePath = Join-Path $root "dist\$releaseName.zip"
    $checksumPath = "$archivePath.sha256"

    foreach ($path in @($workPath, $distPath, $archivePath, $checksumPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "发行路径已存在，不覆盖：$path"
        }
    }

    & $Python -m PyInstaller --noconfirm --workpath $workPath --distpath $distPath mmw-windows.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败"
    }

    Copy-Item -LiteralPath (Join-Path $root "README-Windows.txt") -Destination $bundlePath
    Compress-Archive -Path (Join-Path $bundlePath "*") -DestinationPath $archivePath
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $releaseName.zip" | Set-Content -LiteralPath $checksumPath -Encoding ascii

    Write-Host "Bundle: $bundlePath"
    Write-Host "Archive: $archivePath"
    Write-Host "SHA256: $hash"
}
finally {
    Pop-Location
}
