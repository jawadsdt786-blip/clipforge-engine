@echo off
setlocal
cd /d "%~dp0"
echo.
echo  =============================================
echo          CLIPFORGE - LOCAL VIDEO STUDIO
 echo  =============================================
echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
 echo [ERROR] FFmpeg is not installed or not in your PATH.
 echo Download/install FFmpeg from https://ffmpeg.org/download.html
 echo Reopen this terminal after installing FFmpeg.
 pause
 exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
 echo [ERROR] Python 3.11+ is required. Download from https://python.org/
 pause
 exit /b 1
)
if not exist .venv\Scripts\python.exe (
 echo [1/2] Creating Python environment...
 python -m venv .venv
)
echo [2/2] Installing required packages...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
 echo [ERROR] Dependency installation failed.
 pause
 exit /b 1
)
echo.
echo Open http://127.0.0.1:8000/ in your browser.
echo Keep this window open while using ClipForge.
echo Press Ctrl+C to stop.
echo.
python app.py
pause
