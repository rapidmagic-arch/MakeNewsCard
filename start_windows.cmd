@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if not exist data\newsletter.db (
  .venv\Scripts\python.exe main.py init
  if errorlevel 1 exit /b 1
  .venv\Scripts\python.exe main.py seed-demo
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe main.py serve
