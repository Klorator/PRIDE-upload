@echo off
rem Launcher so the script can be run by double-clicking.
rem Scans the PARENT directory of this tools folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Export-FileLists.ps1"
