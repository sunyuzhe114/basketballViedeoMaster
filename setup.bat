@echo off
cd /d "%~dp0"
python -m pip install -r basketball_master\requirements.txt
if errorlevel 1 goto failed
python -c "from pathlib import Path; import sys; from ultralytics import YOLO; p=Path('basketball_master/models'); p.mkdir(parents=True,exist_ok=True); YOLO(str(p/'yolo11s.pt')); Path('basketball_master/python-path.txt').write_text(str(Path(sys.executable).with_name('pythonw.exe')),encoding='utf-8')"
if errorlevel 1 goto failed
ffmpeg -version >nul 2>&1
if errorlevel 1 goto failed
echo Setup complete.
pause
exit /b 0
:failed
echo Setup failed. Check Python, network, and FFmpeg installation.
pause
exit /b 1
