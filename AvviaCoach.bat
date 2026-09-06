@echo off
rem Avvio di ACEVO Coach. Doppio clic e basta.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   Ambiente Python non trovato in .venv
  echo.
  echo   Crealo una volta sola con questi due comandi:
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" main.py --host 0.0.0.0 %*

rem Se il server esce con errore la finestra resta aperta per farlo leggere.
if errorlevel 1 (
  echo.
  pause
)
