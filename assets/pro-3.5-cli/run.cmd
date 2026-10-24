@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if defined MCGS_PYTHON goto configured
"%SystemRoot%\System32\where.exe" python >nul 2>nul
if not errorlevel 1 goto path_python
if exist "%SystemRoot%\py.exe" goto launcher
echo Python 3.11 or newer is required. Set MCGS_PYTHON to its full executable path. 1>&2
exit /b 3
:configured
"%MCGS_PYTHON%" "%~dp0scripts\mcgs_file.py" %*
exit /b %errorlevel%
:path_python
python "%~dp0scripts\mcgs_file.py" %*
exit /b %errorlevel%
:launcher
"%SystemRoot%\py.exe" -3 "%~dp0scripts\mcgs_file.py" %*
exit /b %errorlevel%
