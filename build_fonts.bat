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

rem 文字ファイル(src\charsvg)を正本として扱うため、原本(drawio)からの再抽出は行いません。
rem 原本から検証等で再抽出を行う場合は手動で "py tools\split_glyphs.py --output-dir src\charsvg --overwrite" を実行してください。

py tools\build_fonts.py --variant both --glyph-dir src\charsvg --output-dir build\fonts
if errorlevel 1 goto failed

if not exist "site\fonts" mkdir "site\fonts"
for %%F in (NGSNoctM NGSNoctM-Bold NGSNoctP NGSNoctP-Bold NGSNoctMF NGSNoctMF-Bold NGSNoctPF NGSNoctPF-Bold) do (
  copy /y "build\fonts\%%F.ttf" "fonts\%%F.ttf" >nul
  if errorlevel 1 goto failed
  copy /y "build\fonts\%%F.woff2" "fonts\%%F.woff2" >nul
  if errorlevel 1 goto failed
  copy /y "build\fonts\%%F.woff2" "site\fonts\%%F.woff2" >nul
  if errorlevel 1 goto failed
)
copy /y "build\fonts\NGSNoct.ttc" "fonts\NGSNoct.ttc" >nul
if errorlevel 1 goto failed
del /q "fonts\NGSNoctMS.ttf" "fonts\NGSNoctMS.woff2" "fonts\NGSNoctMS-Bold.ttf" "fonts\NGSNoctMS-Bold.woff2" "fonts\NGSNoctPS.ttf" "fonts\NGSNoctPS.woff2" "fonts\NGSNoctPS-Bold.ttf" "fonts\NGSNoctPS-Bold.woff2" 2>nul
del /q "site\fonts\NGSNoctMS.woff2" "site\fonts\NGSNoctMS-Bold.woff2" "site\fonts\NGSNoctPS.woff2" "site\fonts\NGSNoctPS-Bold.woff2" 2>nul

echo.
echo Fonts created in build\fonts.
echo Sample-page WOFF2 files copied to site\fonts.
echo NGS Noct M: NGSNoctM.ttf / .woff2
echo NGS Noct P: NGSNoctP.ttf / .woff2
echo NGS Noct MF/PF and Bold variants are also included.
echo All eight faces are in fonts\NGSNoct.ttc.
pause
exit /b 0

:no_python
echo Python launcher py was not found. Install Python 3 and try again.

:failed
echo Build failed. See the error above.
pause
exit /b 1
