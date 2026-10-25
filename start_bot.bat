@echo off
cd /d "%~dp0"
python -m pip install -q -r bot\requirements.txt
:loop
python bot\gateway_bot.py
echo Bot stopped - restarting in 5 seconds (close this window to stop it)...
timeout /t 5 >nul
goto loop
