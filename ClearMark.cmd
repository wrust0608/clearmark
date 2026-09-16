@echo off
setlocal
chcp 65001 >nul
title ClearMark

:menu
cls
echo.
echo   ClearMark - Công cụ nội bộ
echo   =========================
echo.
echo   [1] Mở ứng dụng
echo   [2] Tắt hoàn toàn
echo   [3] Kiểm tra trạng thái
echo   [4] Thoát
echo.
choice /c 1234 /n /m "Chọn [1-4]: "

if errorlevel 4 exit /b 0
if errorlevel 3 goto status
if errorlevel 2 goto stop
if errorlevel 1 goto start

:start
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0clearmark-manager.ps1" start
goto done

:stop
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0clearmark-manager.ps1" stop
goto done

:status
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0clearmark-manager.ps1" status
goto done

:done
echo.
pause
goto menu
