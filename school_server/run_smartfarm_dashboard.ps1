$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PicoRoot = Join-Path $RepositoryRoot "pico"

if (-not (Test-Path (Join-Path $RepositoryRoot ".env"))) {
    throw "Missing .env. Copy .env.example to .env and enter the school settings first."
}

if (-not (Test-Path (Join-Path $RepositoryRoot "config.school.json"))) {
    throw "Missing config.school.json. Copy config.school.example.json and set the Pico COM port."
}

$env:SMARTFARM_SIMULATION = "0"
$env:SMARTFARM_MQTT_MODE = "publish"

Write-Host "Uploading the verified integrated runtime to Pico 2 W"
py -m mpremote connect auto fs mkdir :sensors 2>$null
py -m mpremote connect auto fs cp (Join-Path $PicoRoot "sensors\__init__.py") :sensors/__init__.py
py -m mpremote connect auto fs cp (Join-Path $PicoRoot "sensors\pe350.py") :sensors/pe350.py
py -m mpremote connect auto fs cp (Join-Path $PicoRoot "smartfarm_pins.py") :smartfarm_pins.py
py -m mpremote connect auto fs cp (Join-Path $PicoRoot "smartfarm_runtime.py") :smartfarm_runtime.py

Write-Host "Starting school dashboard: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
