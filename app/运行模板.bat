@echo off
rem Opens the template window (UI only, no Lightroom, no AI)
"%USERPROFILE%\miniconda3\envs\lrmcp\python.exe" "%~dp0main.py"
if errorlevel 1 pause
