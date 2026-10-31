# Read-only inventory. No serial numbers, driver changes or package installation.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $cpus = @(Get-CimInstance Win32_Processor -OperationTimeoutSec 8)
    $osInfo = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 8
    $driverInstalled = $null
    try {
        $driver = Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'" -OperationTimeoutSec 5
        $driverInstalled = $false
        if ($null -ne $driver) {
            $driverPath = [Environment]::ExpandEnvironmentVariables($driver.PathName).Trim('"')
            if ($driverPath.StartsWith('\??\')) { $driverPath = $driverPath.Substring(4) }
            if ($driverPath.StartsWith('\SystemRoot\', [StringComparison]::OrdinalIgnoreCase)) { $driverPath = Join-Path $env:SystemRoot $driverPath.Substring(12) }
            $driverInstalled = ($driver.State -eq 'Running' -or (Test-Path -LiteralPath $driverPath))
        }
    } catch { $driverInstalled = $null }
    $gpus = @()
    foreach ($gpu in @(Get-CimInstance Win32_VideoController -OperationTimeoutSec 8)) {
        $vendor = ''; $device = ''
        if ($gpu.PNPDeviceID -match 'VEN_([0-9A-Fa-f]{4})') { $vendor = $Matches[1].ToUpperInvariant() }
        if ($gpu.PNPDeviceID -match 'DEV_([0-9A-Fa-f]{4})') { $device = $Matches[1].ToUpperInvariant() }
        $gpus += @{name=$gpu.Name; vendorId=$vendor; deviceId=$device; driverVersion=$gpu.DriverVersion; healthy=($gpu.ConfigManagerErrorCode -eq 0)}
    }
    @{state='detected'; architecture=if (@($cpus | Where-Object { $_.Architecture -ne 9 }).Count -eq 0 -and $cpus.Count -gt 0) {'x64'} else {'unsupported'};
      cpu=@{name=(@($cpus.Name) -join ' / '); manufacturer=(@($cpus.Manufacturer | Select-Object -Unique) -join ' / '); logicalProcessors=($cpus.NumberOfLogicalProcessors | Measure-Object -Sum).Sum};
      windowsBuild=[int]$osInfo.BuildNumber; desktop=($osInfo.ProductType -eq 1); gpus=$gpus;
      cpuSensorDriverInstalled=$driverInstalled
    } | ConvertTo-Json -Depth 6 -Compress
} catch {
    @{state='unavailable'; message='Windows hardware inventory could not be read. Automatic setup will use CPU compatibility.'; gpus=@()} | ConvertTo-Json -Compress
}
