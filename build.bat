@echo off
cd /d "%~dp0"
echo === Building PS Store by Slava ===
".venv39\Scripts\pyinstaller.exe" ^
  --noconfirm --clean --onefile --windowed ^
  --name "PS Store by Slava" ^
  --add-data "web;web" ^
  --collect-all webview ^
  --collect-all clr_loader ^
  app.py
echo.
echo === Done. EXE: dist\PS Store by Slava.exe ===
pause
