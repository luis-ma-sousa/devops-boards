@echo off
rem Start Boards on Windows: double-click this file.
setlocal
cd /d "%~dp0"
title Boards

set "PYTHON="
for %%V in (3.13 3.12 3.11) do (
  if not defined PYTHON (
    py -%%V -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PYTHON=py -%%V"
  )
)
if not defined PYTHON (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PYTHON=python"
)
if defined PYTHON (
  %PYTHON% launch.py %*
  goto :done
)

set "UV="
where uv >nul 2>&1 && set "UV=uv"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
  echo Python 3.11 or newer was not found on this computer.
  echo Boards can set it up for you with uv ^(https://astral.sh/uv, no admin rights needed^).
  choice /c YN /m "Set it up now"
  if errorlevel 2 (
    echo Install Python 3.12 from https://www.python.org/downloads/ and run this again.
    goto :done
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
"%UV%" run --python 3.12 --no-project launch.py %*

:done
set "STATUS=%errorlevel%"
if not "%STATUS%"=="0" if not defined BOARDS_NO_PAUSE pause
endlocal & exit /b %STATUS%
