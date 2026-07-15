@echo off
echo ========================================
echo   soroban one-click build (PyInstaller)
echo ========================================

rem ===== Version (edit this on each release) =====
set VERSION=v1.0.0

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend
set RELEASE=%ROOT%Releases\%VERSION%
set VENV_PY=%BACKEND%\.venv\Scripts\python.exe

rem ===== Pick Python: prefer backend venv (start.bat creates it), else system =====
rem NOTE: always call PyInstaller via "python -m PyInstaller" (NOT bare "pyinstaller").
rem This script is named pyinstaller.bat; cmd would resolve "pyinstaller" to THIS file
rem (current dir before PATH) and recurse into an infinite loop.
echo.
echo [0/3] Locating Python ...
if exist "%VENV_PY%" (
    set PY=%VENV_PY%
    echo Using backend venv: %VENV_PY%
) else (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: python not found and backend\.venv missing.
        echo        Run start.bat once to create the venv, or install Python 3.11+.
        pause
        exit /b 1
    )
    set PY=python
    echo Using system python ^(backend\.venv not found; run start.bat first for a clean env^)
)

rem ===== Ensure backend deps + pyinstaller are available in the chosen interpreter =====
"%PY%" -c "import fastapi, uvicorn, sqlmodel, alembic" >nul 2>&1
if %errorlevel% neq 0 (
    echo Backend deps missing, installing from requirements.txt ...
    "%PY%" -m pip install -r "%BACKEND%\requirements.txt"
    if %errorlevel% neq 0 ( echo ERROR: backend deps install failed & pause & exit /b 1 )
)
"%PY%" -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo pyinstaller not found, installing...
    "%PY%" -m pip install pyinstaller
    if %errorlevel% neq 0 ( echo ERROR: pyinstaller install failed & pause & exit /b 1 )
)

rem ===== Prepare release directory =====
echo.
echo [1/3] Cleaning and creating release dir %RELEASE% ...
if exist "%RELEASE%" rmdir /s /q "%RELEASE%"
mkdir "%RELEASE%"
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

rem ===== Build frontend =====
echo.
echo [2/3] Building frontend ...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: npm not found, please install Node.js: https://nodejs.org/
    pause
    exit /b 1
)
pushd "%FRONTEND%"
if not exist "node_modules" (
    echo Installing frontend deps...
    call npm install
    if %errorlevel% neq 0 ( echo ERROR: npm install failed & popd & pause & exit /b 1 )
)
call npm run build
if %errorlevel% neq 0 ( echo ERROR: frontend build failed & popd & pause & exit /b 1 )
popd
if not exist "%FRONTEND%\dist\index.html" (
    echo ERROR: frontend\dist\index.html not found, frontend build may have failed
    pause
    exit /b 1
)

rem ===== Build main program soroban.exe =====
echo.
echo [3/3] Building soroban.exe (console; frontend + Alembic migrations bundled in) ...
"%PY%" -m PyInstaller --clean --noconfirm "%ROOT%soroban.spec" ^
    --distpath "%RELEASE%" --workpath "%ROOT%build"
if %errorlevel% neq 0 (
    echo ERROR: soroban.exe build failed
    pause
    exit /b 1
)

rem frontend\dist and alembic migrations are bundled INTO soroban.exe (see soroban.spec).
rem Scraper plugins (scraper\soroban-scraper-*) are NOT bundled; drop the scraper folder
rem next to soroban.exe to have them discovered (each plugin runs in its own venv).

rem ===== Clean build intermediates =====
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

echo.
echo ========================================
echo   Build complete! Output dir: %RELEASE%
echo ========================================
dir /b "%RELEASE%"
echo ----------------------------------------
echo   Run soroban.exe. It creates soroban.db + .env next to itself on first run,
echo   seeds an admin (admin / admin123), then serves API + frontend on one port.
echo   Open http://127.0.0.1:8620 in your browser (set BACKEND_PORT to change the port).
echo   Ship a "scraper" folder next to the exe if you use crawler plugins.
echo ========================================
pause
