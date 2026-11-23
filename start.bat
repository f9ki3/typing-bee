@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY_CMD="
where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
  where py >nul 2>&1 && set "PY_CMD=py -3"
)

if not defined PY_CMD (
  echo Python not found. Attempting installation via winget...
  where winget >nul 2>&1
  if %errorlevel% equ 0 (
    winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
    set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
    where python >nul 2>&1 && set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo [ERROR] Python was not found and could not be auto-installed.
  echo Please install Python 3 from https://www.python.org/downloads/ and check "Add python.exe to PATH".
  pause
  exit /b 1
)

%PY_CMD% -c "import websockets" >nul 2>&1
if %errorlevel% neq 0 (
  echo Installing required package: websockets...
  %PY_CMD% -m pip install websockets
)

echo Starting Spelling Bee Server...
start "Spelling Bee Server" %PY_CMD% "%~dp0server.py"

timeout /t 2 /nobreak >nul
start "" "http://localhost:8000/teacher.html"