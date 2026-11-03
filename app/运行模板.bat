@echo off
rem 双击打开「修图助手」模板窗口（只是界面，不连接 Lightroom 和 AI）
"%USERPROFILE%\miniconda3\envs\lrmcp\python.exe" "%~dp0main.py"
if errorlevel 1 pause
