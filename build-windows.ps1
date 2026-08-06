param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Push-Location $root
try {
    $version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw "Unable to read project version"
    }

    $releaseName = "MMW-Windows-x64-v$version"
    $environmentPath = Join-Path $root "build\release-env-v$version"
    $workPath = Join-Path $root "build\pyinstaller-v$version"
    $distPath = Join-Path $root "dist\pyinstaller-v$version"
    $bundlePath = Join-Path $distPath "MMW"
    $archivePath = Join-Path $root "dist\$releaseName.zip"
    $checksumPath = "$archivePath.sha256"
    $lockPath = Join-Path $root "requirements-windows.lock"

    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw "Missing Windows dependency lock: $lockPath"
    }

    foreach ($path in @($environmentPath, $workPath, $distPath, $archivePath, $checksumPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "Release path already exists; refusing to overwrite: $path"
        }
    }

    & $Python -m venv $environmentPath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create isolated build environment"
    }
    $buildPython = Join-Path $environmentPath "Scripts\python.exe"
    & $buildPython -m pip install --disable-pip-version-check -r $lockPath
    if ($LASTEXITCODE -ne 0) {
        throw "Release dependency installation failed"
    }
    & $buildPython -m pip install --disable-pip-version-check --no-deps $root
    if ($LASTEXITCODE -ne 0) {
        throw "Project installation failed"
    }

    & $buildPython -m PyInstaller --noconfirm --workpath $workPath --distpath $distPath mmw-windows.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed"
    }

    Copy-Item -LiteralPath (Join-Path $root "README-Windows.txt") -Destination $bundlePath
    Compress-Archive -Path (Join-Path $bundlePath "*") -DestinationPath $archivePath
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $releaseName.zip" | Set-Content -LiteralPath $checksumPath -Encoding ascii

    & $buildPython -m mmw.release_validation `
        --bundle $bundlePath `
        --archive $archivePath `
        --checksum $checksumPath
    if ($LASTEXITCODE -ne 0) {
        throw "Windows release validation failed"
    }

    Write-Host "Build environment: $environmentPath"
    Write-Host "Bundle: $bundlePath"
    Write-Host "Archive: $archivePath"
    Write-Host "SHA256: $hash"
}
finally {
    Pop-Location
}
