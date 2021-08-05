@echo off
echo Installing dependencies...
py -3 -m pip install -r requirements.txt
echo Running
py -3 humblesteamkeysredeemer.py
set /p=Press ENTER to close terminal
