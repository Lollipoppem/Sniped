@echo off
title SNIPED - Roblox Rivals Auto-Clipper
color 0A

echo ==========================================
echo   SNIPED v2.4 - Roblox Rivals Clipper
echo ==========================================
echo.

:: --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo.
    echo Install Python 3.10+ from: https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during install!
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v

:: --- Find FFmpeg ---
ffmpeg -version >nul 2>&1
if not errorlevel 1 goto ffmpeg_ok

echo FFmpeg not in PATH, searching common install locations...
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" (
            set "PATH=%%S\bin;%PATH%"
            goto ffmpeg_ok
        )
    )
)
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\ffmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" (
            set "PATH=%%S\bin;%PATH%"
            goto ffmpeg_ok
        )
    )
)
if exist "C:\Program Files\FFmpeg\bin\ffmpeg.exe" (
    set "PATH=C:\Program Files\FFmpeg\bin;%PATH%"
    goto ffmpeg_ok
)
if exist "C:\ffmpeg\bin\ffmpeg.exe" (
    set "PATH=C:\ffmpeg\bin;%PATH%"
    goto ffmpeg_ok
)
echo.
echo ERROR: FFmpeg installed but cannot be found.
echo Fix: Restart your PC, then try again.
echo Or run in terminal:  winget install ffmpeg
echo.
pause
exit /b 1

:ffmpeg_ok
echo Found: FFmpeg OK
echo.

:: --- Create recordings folder if missing ---
if not exist "recordings\" (
    mkdir recordings
    echo Created "recordings" folder.
    echo Put your MP4 files inside it, then run this script again.
    echo.
    pause
    exit /b 0
)

:: --- Count MP4s ---
set /a count=0
for %%f in ("recordings\*.mp4" "recordings\*.MP4") do set /a count+=1
if %count%==0 (
    echo ERROR: No MP4 files found in recordings\
    echo.
    pause
    exit /b 1
)

echo Found %count% MP4 file(s) in .\recordings\
echo Clips will be saved to .\clips\
echo.
echo Note: EasyOCR downloads ~1GB on first run (PyTorch + model).
echo This is normal and only happens once.
echo.
echo ==========================================

python config.py --input ./recordings --output ./clips

echo.
echo ==========================================
echo  Done! Check the clips folder.
echo ==========================================
echo.
pause
