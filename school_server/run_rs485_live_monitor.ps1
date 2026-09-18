param(
    [double]$Interval = 2
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
py school_server\rs485_live_monitor.py --interval $Interval
