param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
try {
    $installed = Test-Path -LiteralPath 'HKLM:/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/PawnIO'
    if (-not $installed) {
        $installer = Join-Path $Directory 'PawnIO_setup.exe'
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=namazso.eu') { throw 'PawnIO installer signature check failed' }
        # Interactive driver installer. No Windows security settings are changed.
        $setup = Start-Process -FilePath $installer -PassThru -Wait
        if ($setup.ExitCode -ne 0) { throw "PawnIO installation did not complete: $($setup.ExitCode)" }
    }
    if (Test-Path -LiteralPath (Join-Path $Directory 'sensor-stop.flag')) { throw 'This guard has already finished. Bind a new job explicitly before starting again.' }
    $cfg = Get-Content -LiteralPath (Join-Path $Directory 'guard-config.json') -Raw | ConvertFrom-Json
    Start-Process -FilePath $cfg.python -ArgumentList @('-u', ('"'+(Join-Path $Directory 'thermal_guard.py')+'"'), ('"'+(Join-Path $Directory 'guard-config.json')+'"')) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Directory 'guard-output.log') -RedirectStandardError (Join-Path $Directory 'guard-error.log') | Out-Null
    & (Join-Path $Directory 'cpu_sensor.ps1') -Directory $Directory
} catch {
    @{error=$_.Exception.ToString(); state='not_armed'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'setup-error.json') -Encoding UTF8
    & (Join-Path $Directory 'alert.ps1') -Message ('Temperature protection could not start: '+$_.Exception.Message)
    exit 1
}
