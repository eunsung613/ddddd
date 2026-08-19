$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PicoTestFile = Join-Path $RepositoryRoot "pico\i2c_sensor_test.py"

Write-Host "Uploading the I2C test to Pico 2 W"
py -m mpremote connect auto fs cp $PicoTestFile :i2c_sensor_test.py

Write-Host "Starting dashboard: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
