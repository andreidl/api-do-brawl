@echo off
REM ==========================================================
REM  PRIMEIRA publicacao no GitHub (rode uma vez)
REM  Repositorio: https://github.com/andreidl/api-do-brawl
REM ==========================================================
cd /d "%~dp0"

where git >nul 2>nul || (echo ERRO: Git nao instalado. Baixe em https://git-scm.com/download/win e rode de novo. & pause & exit /b 1)
call .venv\Scripts\activate.bat 2>nul

echo Gerando o site estatico (raspa os dados atuais)...
python -m app.exportar

echo.
echo Preparando o repositorio git...
if not exist .git git init
git add -A
git -c user.name="andreidl" -c user.email="anderson.lima@institutofarol.com" commit -m "API do Brawl - primeira publicacao"
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/andreidl/api-do-brawl.git

echo.
echo Enviando para o GitHub... (VAI ABRIR O NAVEGADOR para voce clicar em AUTORIZAR)
git push -u origin main

echo.
echo Se subiu sem erro, me avise que eu ligo o GitHub Pages para voce.
echo Seu site ficara em: https://andreidl.github.io/api-do-brawl/
pause
