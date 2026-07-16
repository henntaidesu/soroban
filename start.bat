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

REM ---- ports (shared by backend + frontend so vite proxy always matches) ----
REM vite.config.js reads BACKEND_PORT/FRONTEND_PORT from the environment; setting
REM them here keeps uvicorn's port and vite's /api proxy target in sync.
if not defined BACKEND_PORT set "BACKEND_PORT=8620"
if not defined FRONTEND_PORT set "FRONTEND_PORT=8621"

REM ---- environment checks ----
where python >nul 2>nul
if errorlevel 1 goto no_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 goto bad_python
where node >nul 2>nul
if errorlevel 1 goto no_node

REM ---- backend deps: create venv if missing; auto-sync when requirements.txt changes ----
if exist "%BACKEND%\.venv" goto venv_ok
echo First run: creating Python venv...
python -m venv "%BACKEND%\.venv"
if errorlevel 1 goto venv_fail
"%PY_BIN%" -m pip install --quiet --upgrade pip
:venv_ok

REM fingerprint requirements.txt (sha256 via python); reinstall only when it changed or first time
set "REQ_STAMP=%BACKEND%\.venv\.requirements.sha256"
for /f "usebackq delims=" %%H in (`python -c "import hashlib;print(hashlib.sha256(open(r'%BACKEND%\requirements.txt','rb').read()).hexdigest())"`) do set "REQ_HASH=%%H"
set "REQ_OLD="
if exist "%REQ_STAMP%" set /p REQ_OLD=<"%REQ_STAMP%"
if not exist "%REQ_STAMP%" goto sync_backend
if "%REQ_HASH%"=="%REQ_OLD%" goto deps_ok
:sync_backend
echo Syncing backend deps (first install or requirements changed)...
"%PY_BIN%" -m pip install --quiet -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto deps_fail
> "%REQ_STAMP%" echo %REQ_HASH%
echo Backend deps ready.
:deps_ok

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

REM ---- frontend deps: install when node_modules missing or package.json changed ----
set "PKG_STAMP=%FRONTEND%\node_modules\.package.sha256"
for /f "usebackq delims=" %%H in (`python -c "import hashlib;print(hashlib.sha256(open(r'%FRONTEND%\package.json','rb').read()).hexdigest())"`) do set "PKG_HASH=%%H"
set "PKG_OLD="
if exist "%PKG_STAMP%" set /p PKG_OLD=<"%PKG_STAMP%"
if not exist "%FRONTEND%\node_modules" goto sync_frontend
if not exist "%PKG_STAMP%" goto sync_frontend
if "%PKG_HASH%"=="%PKG_OLD%" goto front_ok
:sync_frontend
echo Syncing frontend deps (first install or package.json changed)...
pushd "%FRONTEND%"
call npm install
if errorlevel 1 goto front_fail
popd
> "%PKG_STAMP%" echo %PKG_HASH%
echo Frontend deps ready.
:front_ok

REM ---- start ----
REM Run both services in THIS console (no popup windows). Backend runs in the
REM background via "start /b" (its output still prints here); frontend runs in the
REM foreground so this window stays alive. Press Ctrl+C to stop.
echo Starting backend  -^> http://127.0.0.1:%BACKEND_PORT%  (docs at /docs)
start "soroban-backend" /b /d "%BACKEND%" "%UVICORN_BIN%" app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload

echo Starting frontend -^> http://localhost:%FRONTEND_PORT%
echo.
echo soroban started. Default login: admin / admin123
echo Open http://localhost:%FRONTEND_PORT% in your browser. Press Ctrl+C to stop.
echo.
pushd "%FRONTEND%"
call npm run dev
popd
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
:front_fail
echo [X] Failed to install frontend deps.
pause
exit /b 1
:env_fail
echo [X] Failed to generate backend\.env.
pause
exit /b 1
