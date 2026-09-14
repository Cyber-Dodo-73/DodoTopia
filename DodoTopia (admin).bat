@echo off
cd /d "%~dp0"
powershell -Command "Start-Process pyw -ArgumentList app.py -Verb RunAs -WorkingDirectory \"%~dp0\""
