# Build the LULC image and push it to Docker Hub, using the creds in ..\.env.
# Run from anywhere:  powershell -File deploy\build_and_push.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")   # repo root (build context)

# read docker_username / docker_pat out of .env
$envMap = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') { $envMap[$matches[1].Trim()] = $matches[2].Trim() }
}
$user = $envMap["docker_username"]; $pat = $envMap["docker_pat"]
if (-not $user -or -not $pat) { throw "set docker_username and docker_pat in .env" }

$image = "$user/corestack-lulc:latest"

Write-Output "==> docker login as $user"
$pat | docker login -u $user --password-stdin

Write-Output "==> building $image"
docker build -t $image .

Write-Output "==> pushing $image"
docker push $image

docker logout | Out-Null
Write-Output "==> done: $image"
