@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0clearmark-manager.ps1" stop
