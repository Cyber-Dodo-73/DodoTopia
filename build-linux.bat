@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  DodoTopia - construction du bundle Linux (Docker)
echo ============================================================

for /f "tokens=2 delims== " %%v in ('findstr VERSION version.py') do set VERSION=%%~v
set VERSION=%VERSION:"=%
echo Version : %VERSION%

docker --version >nul 2>&1
if errorlevel 1 (
  echo Docker introuvable : installe Docker Desktop et lance-le, puis relance ce script.
  exit /b 1
)

echo.
echo [1/2] Image de construction (Ubuntu 22.04, Python, PyInstaller, Qt)...
docker build -f docker\Dockerfile.linux -t dodotopia-linux .
if errorlevel 1 goto :error

echo.
echo [2/2] Copie de l'archive dans release\ ...
if not exist release mkdir release
docker run --rm -v "%cd%\release:/out" dodotopia-linux
if errorlevel 1 goto :error

echo.
echo Termine : release\DodoTopia-%VERSION%-linux-x64.tar.gz
goto :eof

:error
echo.
echo ERREUR pendant la construction Linux.
exit /b 1
