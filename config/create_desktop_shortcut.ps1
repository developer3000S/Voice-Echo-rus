$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('C:\Users\ravit\OneDrive\Desktop\Voice Echo - Premium.lnk')
$Shortcut.TargetPath = 'D:\TiTech Prabha Solution\Voice AI\Voice AI\Voice-AI---Lite-main\Voice-AI---Lite-main\.venv\Scripts\pythonw.exe'
$Shortcut.Arguments = '"D:\TiTech Prabha Solution\Voice AI\Voice AI\Voice-AI---Lite-main\Voice-AI---Lite-main\main.py"'
$Shortcut.WorkingDirectory = 'D:\TiTech Prabha Solution\Voice AI\Voice AI\Voice-AI---Lite-main\Voice-AI---Lite-main'
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Launch Voice Echo - Premium'
if ('D:\TiTech Prabha Solution\Voice AI\Voice AI\Voice-AI---Lite-main\Voice-AI---Lite-main\assets\Voice_Lite_Logo.ico') { $Shortcut.IconLocation = 'D:\TiTech Prabha Solution\Voice AI\Voice AI\Voice-AI---Lite-main\Voice-AI---Lite-main\assets\Voice_Lite_Logo.ico,0' }
$Shortcut.Save()