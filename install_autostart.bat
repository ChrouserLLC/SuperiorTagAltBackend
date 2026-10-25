@echo off
rem Makes the Discord bot start minimized every time you log in to Windows.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\SuperiorTag Bot.lnk'); $s.TargetPath='%~dp0start_bot.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (echo Something went wrong - nothing was changed.) else (echo Done! The bot will start minimized every time you log in.)
echo To undo it, run remove_autostart.bat
pause
