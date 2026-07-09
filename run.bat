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
REM  * Forces UTF-8 console output so Italian accented chars
REM    render cleanly on any Windows code page.
REM ============================================================

setlocal EnableExtensions
chcp 65001 > nul

cd /d "%~dp0"

REM --- Preferred path: local .venv ----------------------------------
if exist ".venv\Scripts\python.exe" (
    echo.
    echo === Avvio Kokoro Studio ===
    echo     Cartella : %CD%
    echo     Interp.  : .venv\Scripts\python.exe
    echo.

    ".venv\Scripts\python.exe" -m kokoro_studio
    goto :after_run
)

REM --- Fallback: system Python 3.11 via the `py` launcher -----------
echo.
echo [info] .venv non trovato in %CD% - uso il Python di sistema "py -3.11".
echo.

where py > nul 2>&1
if errorlevel 1 (
    echo [ERRORE]  Il launcher 'py' non e' trovato nel PATH.
    echo           Installa Python 3.11 dal sito python.org.
    echo.
    pause
    exit /b 1
)

echo Per un'installazione pulita, crea prima il venv:
echo     py -3.11 -m venv .venv
echo     .venv\Scripts\activate
echo     pip install -r requirements.txt
echo.

echo === Avvio Kokoro Studio (system Python) ===
echo.

py -3.11 -m kokoro_studio

:after_run
set "EXITCODE=%errorlevel%"

echo.
if not "%EXITCODE%"=="0" (
    echo [ERRORE]  Kokoro Studio terminato con codice %EXITCODE%.
    echo           Controlla i messaggi sopra per i dettagli.
) else (
    echo === Kokoro Studio chiuso normalmente ===
)
echo.
pause

endlocal & exit /b %EXITCODE%
