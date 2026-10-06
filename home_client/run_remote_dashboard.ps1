$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepositoryRoot "config.home.json"))) {
    Copy-Item (Join-Path $RepositoryRoot "config.home.example.json") (Join-Path $RepositoryRoot "config.home.json")
    Write-Host "Created config.home.json from the example."
}

$env:SMARTFARM_SIMULATION = "0"
$env:SMARTFARM_AUTOMATION_ENABLED = "0"
$env:SMARTFARM_CONTROL_ENABLED = "0"
$env:SMARTFARM_CHEMICAL_CONTROL_ENABLED = "0"
$env:SMARTFARM_LED_SCHEDULE_HARDWARE_ENABLED = "0"
$env:SMARTFARM_MQTT_PUBLISH_ENABLED = "0"
$env:SMARTFARM_MQTT_SUBSCRIBE_ENABLED = "1"
$env:SMARTFARM_MQTT_CONFIG = "config.home.json"

Write-Host "Starting external MQTT dashboard: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
