# Builds deployment artifacts into code\dist\ (Windows PowerShell).
#   lambda-function.zip         -> upload as the process-uploaded-file function code
#   pymysql-layer.zip           -> upload as a Lambda layer (Python 3.12)
#   insurance-portal-source.zip -> submission ZIP (source + docs, no dependencies)
# Uses tar.exe (built into Windows 10+) because Compress-Archive in Windows PowerShell 5
# writes backslash paths, which Lambda's Linux runtime does not treat as folders.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist"
$build = Join-Path $root "build"

Remove-Item -Recurse -Force $dist, $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $dist, (Join-Path $build "python") | Out-Null

tar -a -cf (Join-Path $dist "lambda-function.zip") -C (Join-Path $root "lambda") lambda_function.py
if ($LASTEXITCODE -ne 0) { throw "Failed to build lambda-function.zip" }

pip install --no-compile -r (Join-Path $root "lambda\requirements.txt") -t (Join-Path $build "python")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
tar -a -cf (Join-Path $dist "pymysql-layer.zip") -C $build python
if ($LASTEXITCODE -ne 0) { throw "Failed to build pymysql-layer.zip" }

tar -a -cf (Join-Path $dist "insurance-portal-source.zip") -C $root `
    README.md package.ps1 frontend backend lambda deploy database iam
if ($LASTEXITCODE -ne 0) { throw "Failed to build insurance-portal-source.zip" }

Remove-Item -Recurse -Force $build
Get-ChildItem $dist
