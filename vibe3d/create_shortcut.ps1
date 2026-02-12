$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\Vibe3D.lnk")
$Shortcut.TargetPath = "C:\Users\User\works\bio\vibe3d\start.bat"
$Shortcut.WorkingDirectory = "C:\Users\User\works\bio"
$Shortcut.Description = "Start Vibe3D Unity Accelerator"
$Shortcut.Save()
Write-Host "Desktop shortcut created: $Desktop\Vibe3D.lnk"
