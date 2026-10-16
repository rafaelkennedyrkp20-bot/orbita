@echo off
rem Orbita - inicia o agente (prepara o ambiente na primeira vez e cria os atalhos).
setlocal
cd /d "%~dp0"

set "PY="
for %%V in (3.12 3.13 3.11 3.14 3.10) do (
    if not defined PY (
        py -%%V --version >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.10 a 3.14 nao foi encontrado.
    echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
    pause
    exit /b 1
)

%PY% "%~dp0launcher.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo O Orbita nao iniciou. Veja data\logs\agent.log ou rode Verificar_Orbita.bat.
    pause
)
exit /b %RESULT%
