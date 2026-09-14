@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  DodoTopia - construction de l'exe et de l'installeur
echo ============================================================

for /f "tokens=2 delims== " %%v in ('findstr VERSION version.py') do set VERSION=%%~v
set VERSION=%VERSION:"=%
echo Version : %VERSION%

rem Interpreteur Python : variable d'environnement PYTHON (ex. "python" en CI), sinon le lanceur py.
if not defined PYTHON set PYTHON=py

echo.
echo [1/4] Dependances Python...
%PYTHON% -m pip install --quiet --upgrade mido keyboard pywebview pyinstaller pillow numpy soundcard websocket-client certifi
if errorlevel 1 goto :error

echo [2/4] Config livree (sans calibrage perso) et icone...
%PYTHON% make_default_config.py
if errorlevel 1 goto :error
%PYTHON% make_version_info.py
if errorlevel 1 goto :error
%PYTHON% -c "from PIL import Image; im=Image.open('assets/logo.png').convert('RGBA'); im.save('assets/logo.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
if errorlevel 1 goto :error

echo [3/4] PyInstaller (dist\DodoTopia\)...
%PYTHON% -m PyInstaller --noconfirm --clean --windowed --name "DodoTopia" ^
  --icon assets\logo.ico --noupx --version-file build\version_info.txt ^
  --add-data "ui;ui" --add-data "assets;assets" --add-data "config.default.json;." ^
  --hidden-import keyboard --hidden-import mido --hidden-import webview ^
  --hidden-import numpy --hidden-import soundcard --collect-data soundcard ^
  --hidden-import websocket --collect-data certifi ^
  --exclude-module _linux_io ^
  --collect-all webview ^
  app.py
if errorlevel 1 goto :error

echo [4/4] Installeur Inno Setup et version portable...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% /Q /DAppVersion=%VERSION% installer.iss
  if errorlevel 1 goto :error
) else (
  echo   Inno Setup introuvable : installeur non genere. winget install JRSoftware.InnoSetup
)
if not exist release mkdir release
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\DodoTopia\*' -DestinationPath 'release\DodoTopia-%VERSION%-portable.zip'"

echo.
echo Termine. Fichiers dans le dossier release\ :
dir /b release
goto :eof

:error
echo.
echo ERREUR pendant la construction.
exit /b 1
