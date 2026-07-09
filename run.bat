@echo off
REM ============================================================
REM  Kokoro Studio launcher (Windows)
REM
REM  Double-click (or pin to Start menu) to launch the GUI.
REM
REM  * Anchors CWD to this script's folder so it works from
REM    any shortcut / pinned icon.
REM  * Prefers the local .venv's Python; falls back to
REM    "py -3.11" (system Python launcher) if .venv is missing.
REM  * Runs `python -m kokoro_studio` -- the `-m` flag is what
REM    lets Python resolve the `kokoro_studio` package and its
REM    `from kokoro_studio....` imports.
REM  * Forces UTF-8 console output so non-ASCII / accented
REM    characters render cleanly on any Windows code page.
REM ============================================================

setlocal EnableExtensions
chcp 65001 > nul

cd /d "%~dp0"

REM --- Preferred path: local .venv ----------------------------------
if exist ".venv\Scripts\python.exe" (
    echo.
    echo === Launching Kokoro Studio ===
    echo     Folder : %CD%
    echo     Python : .venv\Scripts\python.exe
    echo.

    ".venv\Scripts\python.exe" -m kokoro_studio
    goto :after_run
)

REM --- Fallback: system Python 3.11 via the `py` launcher -----------
echo.
echo [info] .venv not found in %CD% - falling back to system Python "py -3.11".
echo.

where py > nul 2>&1
if errorlevel 1 (
    echo [ERROR]  The 'py' launcher is not on PATH.
    echo           Install Python 3.11 from python.org.
    echo.
    pause
    exit /b 1
)

echo For a clean installation, create the venv first:
echo     py -3.11 -m venv .venv
echo     .venv\Scripts\activate
echo     pip install -r requirements.txt
echo.

echo === Launching Kokoro Studio (system Python) ===
echo.

py -3.11 -m kokoro_studio

:after_run
set "EXITCODE=%errorlevel%"

echo.
if not "%EXITCODE%"=="0" (
    echo [ERROR]  Kokoro Studio exited with code %EXITCODE%.
    echo           Check the messages above for details.
) else (
    echo === Kokoro Studio closed normally ===
)
echo.
pause

endlocal & exit /b %EXITCODE%
