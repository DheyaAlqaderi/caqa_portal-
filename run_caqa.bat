@echo off
cd /d "%~dp0"
title CAQA Yemen - Accreditation System

echo =========================================================================
echo    Council for Accreditation and Quality Assurance (CAQA Yemen)
echo    Server starting at: http://127.0.0.1:8000/
echo =========================================================================
echo.

"..\venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
pause
