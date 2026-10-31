param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
$computer = $null
try {
    Add-Type -Path (Join-Path $Directory 'LibreHardwareMonitor/LibreHardwareMonitorLib.dll')
    $computer = New-Object LibreHardwareMonitor.Hardware.Computer
    $computer.IsCpuEnabled = $true
    $computer.Open()
    while (-not (Test-Path -LiteralPath (Join-Path $Directory 'sensor-stop.flag'))) {
        $readings = @()
        foreach ($cpu in $computer.Hardware) {
            if ($cpu.HardwareType.ToString() -ne 'Cpu') { continue }
            $cpu.Update()
            foreach ($sensor in $cpu.Sensors) {
                if ($sensor.SensorType.ToString() -eq 'Temperature' -and $sensor.Name -notmatch 'Distance' -and $null -ne $sensor.Value -and $sensor.Value -gt 1 -and $sensor.Value -lt 130) {
                    $readings += @{name=$sensor.Name; c=[double]$sensor.Value; id=$sensor.Identifier.ToString()}
                }
            }
        }
        if ($readings.Count -eq 0) { throw 'No CPU temperature readings. PawnIO driver and administrator access are required.' }
        $sample = @{timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0; maximumC=($readings.c | Measure-Object -Maximum).Maximum; sensors=$readings; sensorPid=$PID}
        $tempPath = Join-Path $Directory 'cpu-sample.tmp'
        $sample | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination (Join-Path $Directory 'cpu-sample.json') -Force
        Start-Sleep -Seconds 2
    }
} catch {
    @{timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); error=$_.Exception.ToString()} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'sensor-error.json') -Encoding UTF8
    exit 1
} finally {
    if ($null -ne $computer) { $computer.Close() }
}
