@echo off
chcp 65001 >nul
"%~dp0_motor\venv\Scripts\python.exe" "%~dp0_motor\cortes.py" %*
