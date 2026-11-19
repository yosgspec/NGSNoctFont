@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>nul
if errorlevel 1 goto no_python

py -c "import fontTools, shapely, brotli" >nul 2>nul
if errorlevel 1 (
    py -m pip install -r tools\requirements-fonts.txt
    if errorlevel 1 goto failed
)

py tools\split_glyphs.py --output-dir build\charsvg --overwrite
if errorlevel 1 goto failed

py tools\build_fonts.py --variant both --glyph-dir build\charsvg --output-dir build\fonts
if errorlevel 1 goto failed

if not exist "site\fonts" mkdir "site\fonts"
copy /y "build\fonts\NGSNoctM.woff2" "site\fonts\NGSNoctM.woff2" >nul
if errorlevel 1 goto failed
copy /y "build\fonts\NGSNoctP.woff2" "site\fonts\NGSNoctP.woff2" >nul
if errorlevel 1 goto failed

echo.
echo Fonts created in build\fonts.
echo Sample-page WOFF2 files copied to site\fonts.
echo NGS Noct M: NGSNoctM.ttf / .woff2
echo NGS Noct P: NGSNoctP.ttf / .woff2
pause
exit /b 0

:no_python
echo Python launcher py was not found. Install Python 3 and try again.

:failed
echo Build failed. See the error above.
pause
exit /b 1