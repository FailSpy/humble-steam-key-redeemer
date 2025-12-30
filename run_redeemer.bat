@echo off

REM 1. Check if the venv folder exists. If not, create it.
if not exist venv (
    echo Creating virtual environment...
    py -3 -m venv venv
)

REM 2. Activate the virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM 3. Install dependencies (now inside the venv)
echo Installing dependencies...
pip install -r requirements.txt

REM 4. Run the script (using the venv's python)
echo Running...
python humblesteamkeysredeemer.py

set /p=Press ENTER to close terminal