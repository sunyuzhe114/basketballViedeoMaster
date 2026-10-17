@echo off
cd /d "%~dp0"
python -m basketball_master
if errorlevel 1 pause
