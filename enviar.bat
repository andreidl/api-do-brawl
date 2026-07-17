@echo off
REM Reenvia para o GitHub (so o push). Watch: vai abrir o navegador para AUTORIZAR.
cd /d "%~dp0"
echo Enviando para https://github.com/andreidl/api-do-brawl ...
echo (Se abrir uma janela do navegador, clique em AUTORIZAR / AUTHORIZE)
echo.
git push -u origin main
echo.
echo Se apareceu erro em vermelho acima, me copie o texto.
echo Se terminou sem erro, me avise que eu ligo o Pages.
pause
