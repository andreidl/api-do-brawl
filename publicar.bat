@echo off
REM ============================================
REM  Publica o site estatico no GitHub Pages
REM  Pre-requisito: repo git com remote configurado (ver PUBLICAR.md)
REM ============================================
cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo Gerando o site estatico (raspa os dados atuais)...
python -m app.exportar
if errorlevel 1 (echo ERRO ao gerar. & pause & exit /b 1)

echo.
echo Publicando no GitHub...
git add docs
git commit -m "Atualiza site do cla"
git push
echo.
echo Pronto! O cla ja pode abrir o link do GitHub Pages.
pause
