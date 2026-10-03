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
%PYTHON% -m pip install --quiet --upgrade mido keyboard pywebview pyinstaller pillow numpy soundcard websocket-client certifi pynacl pypresence cryptography
if errorlevel 1 goto :error

echo [2/4] Config livree (sans calibrage perso) et icone...
%PYTHON% make_default_config.py
if errorlevel 1 goto :error
%PYTHON% make_version_info.py
if errorlevel 1 goto :error
%PYTHON% make_icon.py
if errorlevel 1 goto :error
%PYTHON% .tools\make_legal.py
if errorlevel 1 goto :error

echo [3/4] PyInstaller (dist\DodoTopia\)...
%PYTHON% -m PyInstaller --noconfirm --clean --windowed --name "DodoTopia" ^
  --icon assets\logo.ico --noupx --version-file build\version_info.txt ^
  --add-data "ui;ui" --add-data "legal;legal" --add-data "config.default.json;." ^
  --add-data "assets\logo.ico;assets" --add-data "assets\logo-256.png;assets" ^
  --add-data "assets\instruments\catalogue.json;assets\instruments" ^
  --add-data "assets\instruments\layouts.json;assets\instruments" ^
  --add-data "assets\instruments\CREDITS.md;assets\instruments" ^
  --hidden-import keyboard --hidden-import mido --hidden-import webview ^
  --hidden-import numpy --hidden-import soundcard --collect-data soundcard ^
  --hidden-import websocket --collect-data certifi --hidden-import nacl --hidden-import cryptography ^
  --exclude-module _linux_io ^
  --collect-all webview ^
  app.py
if errorlevel 1 goto :error

rem Signature Authenticode (facultative) : definir DODO_SIGN_PFX (chemin du .pfx) et DODO_SIGN_PWD, ou
rem DODO_SIGN_CMD (commande complete, ex. Azure Trusted Signing) qui recoit le fichier a signer en argument.
call :sign "dist\DodoTopia\DodoTopia.exe"
if errorlevel 1 goto :error

echo [4/4] Installeur Inno Setup et version portable...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% /Q /DAppVersion=%VERSION% installer.iss
  if errorlevel 1 goto :error
  call :sign "release\DodoTopia-%VERSION%-Setup.exe"
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

:sign
if defined DODO_SIGN_CMD (
  echo   Signature de %~1 ...
  %DODO_SIGN_CMD% %1
  exit /b %errorlevel%
)
if defined DODO_SIGN_PFX (
  echo   Signature de %~1 ...
  signtool sign /f "%DODO_SIGN_PFX%" /p "%DODO_SIGN_PWD%" /fd sha256 /tr http://timestamp.digicert.com /td sha256 %1
  exit /b %errorlevel%
)
exit /b 0

:error
echo.
echo ERREUR pendant la construction.
exit /b 1
