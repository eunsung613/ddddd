$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PicoRoot = Join-Path $RepositoryRoot "pico"
$EnvFile = Join-Path $RepositoryRoot ".env"

if (-not (Test-Path $EnvFile)) {
    throw "Missing .env. Copy .env.example to .env and enter the school settings first."
}

if (-not (Test-Path (Join-Path $RepositoryRoot "config.school.json"))) {
    throw "Missing config.school.json. Copy config.school.example.json and set the Pico COM port."
}

$EnvValues = @{}
Get-Content $EnvFile | ForEach-Object {
    $Line = $_.Trim()
    if ($Line -and -not $Line.StartsWith("#") -and $Line.Contains("=")) {
        $Name, $Value = $Line.Split("=", 2)
        $EnvValues[$Name.Trim()] = $Value.Trim()
    }
}

if ($EnvValues["SMARTFARM_PICO_UPLOAD_ENABLED"] -eq "1") {
    Write-Host "Uploading the verified integrated runtime to Pico 2 W"
    py -m mpremote connect auto fs mkdir :sensors 2>$null
    py -m mpremote connect auto fs cp (Join-Path $PicoRoot "sensors\__init__.py") :sensors/__init__.py
    py -m mpremote connect auto fs cp (Join-Path $PicoRoot "sensors\pe350.py") :sensors/pe350.py
    py -m mpremote connect auto fs cp (Join-Path $PicoRoot "smartfarm_pins.py") :smartfarm_pins.py
    py -m mpremote connect auto fs cp (Join-Path $PicoRoot "smartfarm_runtime.py") :smartfarm_runtime.py
} else {
    Write-Host "Skipping Pico runtime upload (SMARTFARM_PICO_UPLOAD_ENABLED is not 1)"
}

Write-Host "Starting school dashboard: http://127.0.0.1:8765"
Set-Location $RepositoryRoot
py -m dashboard.server
