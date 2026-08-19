$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$TestFile = Join-Path $RepositoryRoot "pico\i2c_sensor_test.py"

Write-Host "Running Pico 2 W I2C sensor test"
Write-Host "Close Thonny first if the serial port is busy."

py -m mpremote connect auto run $TestFile
