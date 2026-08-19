$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepositoryRoot "config.home.json"))) {
    throw "Missing config.home.json. Copy config.home.example.json first."
}

$env:SMARTFARM_SIMULATION = "0"
$env:SMARTFARM_MQTT_MODE = "subscribe"
$env:SMARTFARM_AUTOMATION_ENABLED = "0"
$env:SMARTFARM_CONTROL_ENABLED = "0"
$env:SMARTFARM_CHEMICAL_CONTROL_ENABLED = "0"

Write-Host "Starting external MQTT dashboard: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
