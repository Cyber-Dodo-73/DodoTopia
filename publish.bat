@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  DodoTopia - publication d'une version sur le serveur
echo ============================================================

for /f "tokens=2 delims== " %%v in ('findstr VERSION version.py') do set VERSION=%%~v
set VERSION=%VERSION:"=%
echo Version : %VERSION%

set OPTS=
set DO_BUILD=0
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="--build" (set DO_BUILD=1) else (set OPTS=%OPTS% %1)
shift
goto :parse
:parsed

if "%DO_BUILD%"=="1" (
  echo.
  echo [0/2] Construction via build.bat...
  call build.bat
  if errorlevel 1 goto :error
)

echo.
echo [1/2] Verification des artefacts dans release\...
if not exist "release\DodoTopia-%VERSION%-Setup.exe" (
  echo ERREUR : release\DodoTopia-%VERSION%-Setup.exe introuvable. Lance build.bat d'abord.
  goto :error
)
if not exist "release\DodoTopia-%VERSION%-portable.zip" (
  echo ERREUR : release\DodoTopia-%VERSION%-portable.zip introuvable. Lance build.bat d'abord.
  goto :error
)
if not exist "release\DodoTopia-%VERSION%-linux-x64.tar.gz" (
  echo Avertissement : release\DodoTopia-%VERSION%-linux-x64.tar.gz absent ^(build-linux.bat^) : pas de version Linux.
)

set NOTES=
if exist CHANGELOG.md set NOTES=--notes-file CHANGELOG.md

echo.
if not defined PYTHON set PYTHON=py
echo [2/2] Publication (PUBLISH_URL / PUBLISH_TOKEN depuis l'environnement ou publish.env)...
%PYTHON% publish_release.py --version %VERSION% %NOTES% %OPTS%
if errorlevel 1 goto :error

echo.
echo Termine : la version %VERSION% est en ligne.
goto :eof

:error
echo.
echo ERREUR pendant la publication.
exit /b 1
