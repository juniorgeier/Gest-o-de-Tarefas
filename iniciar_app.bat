@echo off
cd /d "%~dp0"
echo Iniciando servidor em http://localhost:8000 ...
start "" http://localhost:8000
python server.py
