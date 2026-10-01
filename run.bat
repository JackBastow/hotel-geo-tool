@echo off
setlocal enabledelayedexpansion
REM Hotel AI Discoverability Audit - launcher

cd /d "%~dp0"
echo.
echo ================================================
echo   Hotel AI Discoverability Audit
echo ================================================
echo.

REM --- Guard: cloud-synced folders corrupt virtual environments -------------
echo %CD% | findstr /I /C:"OneDrive" >nul
if not errorlevel 1 goto :cloudwarn
echo %CD% | findstr /I /C:"Dropbox" >nul
if not errorlevel 1 goto :cloudwarn
echo %CD% | findstr /I /C:"Google Drive" >nul
if not errorlevel 1 goto :cloudwarn
goto :cloudok

:cloudwarn
echo  *** PROBLEM: this folder is inside a cloud-synced location. ***
echo.
echo  Current location:
echo    %CD%
echo.
echo  A Python environment is thousands of small files. OneDrive syncs them
echo  while they are still being written, which corrupts the install and
echo  can break the app later at random.
echo.
echo  Move this whole folder somewhere local first, for example:
echo    C:\Tools\hotel-geo-tool
echo.
echo  Then delete the .venv folder if one exists, and run this again.
echo.
choice /C YN /M "Continue anyway (not recommended)"
if errorlevel 2 exit /b 1
echo.

:cloudok

REM --- Python present? ------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo  Python was not found.
  echo.
  echo  Install it from https://www.python.org/downloads/
  echo  IMPORTANT: tick "Add Python to PATH" during installation.
  echo.
  pause
  exit /b 1
)
echo [1/4] Python found.
python --version

REM --- Detect a corrupted environment ---------------------------------------
if exist ".venv\Lib\site-packages\~*" (
  echo.
  echo [!] A previous install was interrupted and left corrupted files.
  echo     Rebuilding the environment from scratch.
  rmdir /s /q ".venv" 2>nul
)

REM --- Build the environment ------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
  if exist ".venv" rmdir /s /q ".venv" 2>nul
  echo.
  echo [2/4] Creating environment - first run only...
  python -m venv ".venv"
  if errorlevel 1 (
    echo.
    echo  Could not create the environment.
    echo  If this folder is on a network drive or cloud-synced folder,
    echo  move it to a local path such as C:\Tools\hotel-geo-tool.
    pause
    exit /b 1
  )
) else (
  echo.
  echo [2/4] Environment already set up.
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo  Could not activate the environment. Delete the .venv folder and retry.
  pause
  exit /b 1
)

REM --- Install dependencies. NOT quiet - silence looks like a hang. ---------
echo.
echo [3/4] Checking dependencies. First run downloads about 40MB
echo       and can take 2-3 minutes. Progress will show below.
echo.
python -m pip install --upgrade pip --disable-pip-version-check
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo  Dependency install failed.
  echo  If you are behind a corporate proxy, you may need:
  echo    python -m pip install -r requirements.txt --proxy http://yourproxy:port
  echo.
  pause
  exit /b 1
)

REM --- Confirm streamlit actually landed ------------------------------------
python -c "import streamlit" 2>nul
if errorlevel 1 (
  echo.
  echo  Streamlit did not install correctly.
  echo  Delete the .venv folder and run this again.
  pause
  exit /b 1
)

echo.
echo [4/4] Starting the app. Your browser will open in a few seconds.
echo.
echo  Leave this window open while you use the app.
echo  Close it, or press Ctrl+C, to stop.
echo.

python -m streamlit run app.py

echo.
echo App stopped.
pause
