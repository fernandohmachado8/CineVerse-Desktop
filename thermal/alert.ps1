param([string]$Message)
Add-Type -AssemblyName System.Windows.Forms
[System.Media.SystemSounds]::Exclamation.Play()
[System.Windows.Forms.MessageBox]::Show($Message, 'CineVerse temperature guard', 'OK', 'Warning') | Out-Null
