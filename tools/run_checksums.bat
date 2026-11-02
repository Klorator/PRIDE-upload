@echo off
rem Launcher so the script can be run by double-clicking.
rem Reads checksum_input.txt in this folder and writes checksum.txt in this folder.
python "%~dp0make_checksums.py"
if errorlevel 9009 (
    echo Python was not found on PATH. Install Python 3.6+ or add it to PATH.
    pause
)
