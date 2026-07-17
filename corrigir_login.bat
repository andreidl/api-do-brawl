@echo off
REM Apaga credencial antiga do GitHub e reenvia forcando novo login (andreidl)
cd /d "%~dp0"

echo Limpando credenciais antigas do GitHub no Windows...
cmdkey /delete:git:https://github.com >nul 2>nul
cmdkey /delete:LegacyGeneric:target=git:https://github.com >nul 2>nul
cmdkey /delete:git:https://andreidl@github.com >nul 2>nul
(echo protocol=https&echo host=github.com&echo.)| git credential reject 2>nul
(echo protocol=https&echo host=github.com&echo.)| git credential-manager erase 2>nul

echo.
echo Agora reenviando. VAI ABRIR O NAVEGADOR:
echo   -^> faca login / confirme a conta ANDREIDL e clique AUTORIZAR.
echo.
git push -u origin main

echo.
echo Se subiu sem erro, me avise. Se der 403 de novo, me copie o texto.
pause
