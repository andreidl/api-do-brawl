@echo off
REM ==========================================================
REM  Publica o app + site no GitHub (envio que sobrescreve).
REM  Rode este. Depois o Claude ajusta o Pages para /docs.
REM ==========================================================
cd /d "%~dp0"
where git >nul 2>nul || (echo Instale Git for Windows em git-scm.com & pause & exit /b 1)
call .venv\Scripts\activate.bat 2>nul

echo Gerando o site estatico (v26 - links corrigidos)...
python -m app.exportar

echo.
echo Enviando ao GitHub...
git add -A
git -c user.name="andreidl" -c user.email="anderson.lima@institutofarol.com" commit -m "App + site atualizados (v26)"
git branch -M main
git push -f origin main

echo.
echo Se subiu sem erro, ME AVISE: eu ajusto o GitHub Pages para a pasta /docs
echo e o site volta ao ar com tudo certo em https://andreidl.github.io/api-do-brawl/
pause
