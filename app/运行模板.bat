@echo off
rem Opens the app window with no console window (pythonw). Use the debug .bat to see error messages.
start "" "%USERPROFILE%\miniconda3\envs\lrmcp\pythonw.exe" "%~dp0main.py"
