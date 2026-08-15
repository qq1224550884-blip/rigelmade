$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$webRoot = Join-Path $root "web\web"

function Ready([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}

if (-not (Ready "http://127.0.0.1:8792/api/health")) {
    Start-Process -FilePath powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$root\start-commercial.ps1`" -Port 8792" -WorkingDirectory $root -WindowStyle Hidden | Out-Null
}
if (-not (Ready "http://127.0.0.1:3002/login")) {
    Start-Process -FilePath "C:\Program Files\nodejs\npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory $webRoot -WindowStyle Hidden | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ((Ready "http://127.0.0.1:8792/api/health") -and (Ready "http://127.0.0.1:3002/login")) {
        Start-Process "http://127.0.0.1:3002/login"
        Write-Host "Commercial app ready: http://127.0.0.1:3002/login"
        exit 0
    }
    Start-Sleep -Seconds 1
}
throw "Commercial app did not become ready within 30 seconds. Check H:\desktop-workspace\ai-render-commercial."
