param(
    [Parameter(Mandatory=$true)][string]$Directory,
    [Parameter(Mandatory=$true)][string]$Library,
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][long]$ParentCreated,
    [switch]$IncludeAmdGpu
)
# Read-only sensor helper. It exits with its exact parent instance; no converter
# runs elevated and no Windows security or power setting is changed.
$ErrorActionPreference = 'Stop'
$computer = $null
try {
    @{state='initializing'; parentPid=$ParentPid; expectedCreated=$ParentCreated; sensorPid=$PID} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'sensor-session.json') -Encoding UTF8
    Add-Type -Path $Library
    $computer = New-Object LibreHardwareMonitor.Hardware.Computer
    $computer.IsCpuEnabled = $true
    $computer.IsGpuEnabled = [bool]$IncludeAmdGpu
    $computer.Open()
    while ($true) {
        $parent = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if ($null -eq $parent -or $parent.StartTime.ToUniversalTime().ToFileTimeUtc() -ne $ParentCreated) { throw 'The parent application ended or its creation time changed.' }
        $readings = @()
        foreach ($cpu in $computer.Hardware) {
            if ($cpu.HardwareType.ToString() -ne 'Cpu') { continue }
            $cpu.Update()
            foreach ($sensor in $cpu.Sensors) {
                if ($sensor.SensorType.ToString() -eq 'Temperature' -and $sensor.Name -notmatch 'Distance' -and $null -ne $sensor.Value -and $sensor.Value -gt 1 -and $sensor.Value -lt 130) {
                    $readings += @{name=$sensor.Name; c=[double]$sensor.Value}
                }
            }
        }
        if ($readings.Count -eq 0) { throw 'No CPU readings. Install PawnIO and approve sensor administrator access.' }
        $amdGpus = @()
        if ($IncludeAmdGpu) {
            foreach ($gpu in $computer.Hardware) {
                if ($gpu.HardwareType.ToString() -ne 'GpuAmd') { continue }
                $gpu.Update()
                $gpuReadings = @()
                foreach ($sensor in $gpu.Sensors) {
                    if ($sensor.SensorType.ToString() -eq 'Temperature' -and $null -ne $sensor.Value) {
                        $gpuReadings += @{name=$sensor.Name; c=[double]$sensor.Value}
                    }
                }
                $amdGpus += @{name=$gpu.Name; id=$gpu.Identifier.ToString(); hardwareType='GpuAmd'; sensors=$gpuReadings}
            }
        }
        $sample = @{timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0; sensors=$readings; amdGpus=$amdGpus; sensorPid=$PID}
        $tempPath = Join-Path $Directory 'cpu-sample.tmp'
        $sample | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination (Join-Path $Directory 'cpu-sample.json') -Force
        Start-Sleep -Seconds 2
    }
} catch {
    @{error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'sensor-error.json') -Encoding UTF8
    exit 1
} finally {
    if ($null -ne $computer) { $computer.Close() }
}
