# Capture one sample log per LOG_LEVEL, driving the SAME request sequence each time so the only
# variable between the three files is the level.
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\mrsal\Downloads\summer_attempt2"
$out = "docs\logging_samples"

function Stop-App {
  Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force }
  Start-Sleep 3
}

function Send-Traffic {
  # 1. a plain GET
  curl.exe -s "http://localhost:8000/api/health" | Out-Null
  # 2. a GET carrying a query string
  curl.exe -s "http://localhost:8000/api/hierarchy/export?since=0" | Out-Null
  # 3. a job: trigger -> compute -> outcome
  curl.exe -s -X POST "http://localhost:8000/api/jobs" -H "Content-Type: application/json" `
    -d '{\"op\":\"export\",\"params\":{\"retrain\":{\"node\":\"greenery\"},\"export\":false}}' | Out-Null
  # 4. a GET with credentials in the query string, to show redaction
  curl.exe -s "http://localhost:8000/api/health?token=supersecret123&password=hunter2" | Out-Null
  Start-Sleep 2
}

foreach ($lvl in @("info", "debug", "error")) {
  Write-Output "=== capturing $lvl ==="
  Stop-App
  Remove-Item -Recurse -Force data\logs -ErrorAction SilentlyContinue
  $env:LOG_LEVEL = $lvl
  Start-Process -FilePath ".venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","backend:app","--app-dir","src","--port","8000" -WindowStyle Hidden
  do {
    Start-Sleep -Seconds 3
    try { Invoke-RestMethod "http://localhost:8000/api/health" -TimeoutSec 5 | Out-Null; $up = $true }
    catch { $up = $false }
  } until ($up)
  Send-Traffic
  Copy-Item data\logs\corestack-lulc\app.log "$out\app.$lvl.log" -Force
  $n = (Get-Content "$out\app.$lvl.log" -Encoding UTF8 | Measure-Object -Line).Lines
  Write-Output "  -> $out\app.$lvl.log  ($n lines)"
}
Stop-App
Write-Output "done"
