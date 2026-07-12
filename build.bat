@echo off
rem Build L2DropSpoilGen.exe (onefile, console). Run from this folder.
python -m PyInstaller --onefile --noconsole --clean --noconfirm ^
  --name L2DropSpoilGen ^
  --version-file version_info.txt ^
  --add-data "tools;tools" ^
  l2dropspoilgen.py
echo.
echo Output: dist\L2DropSpoilGen.exe
