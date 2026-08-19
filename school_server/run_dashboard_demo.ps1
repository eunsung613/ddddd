$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$env:SMARTFARM_SIMULATION = "1"
$env:SMARTFARM_MQTT_MODE = "off"
$env:SMARTFARM_AUTOMATION_ENABLED = "0"
$env:SMARTFARM_CONTROL_ENABLED = "0"
$env:SMARTFARM_CHEMICAL_CONTROL_ENABLED = "0"

Write-Host "Starting safe gaming-laptop demo: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
