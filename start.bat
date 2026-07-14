@echo off
REM soroban one-click launcher for Windows.
REM First run: creates venv, installs deps, seeds admin. After that just starts backend + frontend.
REM Usage: double-click, or run start.bat in a terminal.
REM Backend and frontend each open their own window; close a window to stop that service.
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "PY_BIN=%BACKEND%\.venv\Scripts\python.exe"
set "UVICORN_BIN=%BACKEND%\.venv\Scripts\uvicorn.exe"

REM ---- environment checks ----
where python >nul 2>nul
if errorlevel 1 goto no_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 goto bad_python
where node >nul 2>nul
if errorlevel 1 goto no_node

REM ---- backend first-time setup ----
if exist "%BACKEND%\.venv" goto venv_ok
echo First run: creating Python venv and installing backend deps...
python -m venv "%BACKEND%\.venv"
if errorlevel 1 goto venv_fail
"%PY_BIN%" -m pip install --quiet --upgrade pip
"%PY_BIN%" -m pip install --quiet -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto deps_fail
echo Backend deps installed.
:venv_ok

REM .env: generate from template with a random SECRET_KEY if missing
if exist "%BACKEND%\.env" goto env_ok
"%PY_BIN%" -c "import re,secrets,os; b=r'%BACKEND%'; t=open(os.path.join(b,'.env.example'),encoding='utf-8').read(); t=re.sub(r'(?m)^SECRET_KEY=.*','SECRET_KEY='+secrets.token_hex(32),t); open(os.path.join(b,'.env'),'w',encoding='utf-8').write(t)"
if errorlevel 1 goto env_fail
echo Generated backend\.env with a random SECRET_KEY.
:env_ok

REM create/confirm admin account (idempotent)
pushd "%BACKEND%"
"%PY_BIN%" -m app.seed
popd

REM ---- frontend first-time setup ----
if exist "%FRONTEND%\node_modules" goto front_ok
echo First run: installing frontend deps (npm install)...
pushd "%FRONTEND%"
call npm install
popd
:front_ok

REM ---- start ----
echo Starting backend  -^> http://127.0.0.1:8000  (docs at /docs)
start "soroban-backend" /d "%BACKEND%" cmd /k ""%UVICORN_BIN%" app.main:app --host 127.0.0.1 --port 8000 --reload"

echo Starting frontend -^> http://localhost:5173
start "soroban-frontend" /d "%FRONTEND%" cmd /k "npm run dev"

echo.
echo soroban started. Default login: admin / admin123
echo Open http://localhost:5173 in your browser. Close the two popup windows to stop.
echo.
pause
goto :eof

:no_python
echo [X] python not found. Install Python 3.11+ and check "Add python to PATH".
pause
exit /b 1
:bad_python
echo [X] Python 3.11+ required (plugin uses stdlib tomllib). Current version:
python -V
pause
exit /b 1
:no_node
echo [X] node not found (needed for the frontend).
pause
exit /b 1
:venv_fail
echo [X] Failed to create the Python venv.
pause
exit /b 1
:deps_fail
echo [X] Failed to install backend deps.
pause
exit /b 1
:env_fail
echo [X] Failed to generate backend\.env.
pause
exit /b 1
