@echo off
chcp 65001 >nul
title Painel da Fabrica de Cortes
echo Painel abrindo no navegador (http://localhost:8765).
echo Deixe esta janela aberta; feche para desligar o painel.
"%~dp0_motor\venv\Scripts\python.exe" "%~dp0_motor\cortes.py" painel
pause
