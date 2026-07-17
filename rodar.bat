@echo off
REM ============================================
REM  API do Brawl - subir o site com 2 cliques
REM ============================================
cd /d "%~dp0"

if not exist requirements.txt (
  echo ERRO: coloque este rodar.bat na pasta do projeto ^(onde esta o requirements.txt^).
  pause
  exit /b 1
)

REM cria o venv na primeira vez
if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv || (echo ERRO: Python nao encontrado no PATH. Instale em python.org e marque "Add to PATH". & pause & exit /b 1)
)

call .venv\Scripts\activate.bat

echo Instalando/conferindo dependencias...
pip install -q -r requirements.txt

REM importa/atualiza os historicos do Brawlify (idempotente, offline, rapido)
echo Importando historicos do Brawlify...
python -m app.importar_brawlify dados_brawlify
if exist dados_brawlify_camila (
  python -m app.importar_brawlify dados_brawlify_camila "#2QLLLGV0R0" 2026-07-17=51673
)
if exist dados_brawlify_bigboss (
  python -m app.importar_brawlify dados_brawlify_bigboss "#9029RVG2J" 2026-07-17=65704
)
if exist dados_brawlify_gustavo (
  python -m app.importar_brawlify dados_brawlify_gustavo "#28GY9QJVC" 2026-07-16=68766
)

echo.
echo Abrindo http://localhost:8000 ...
start "" http://localhost:8000
echo Servidor rodando. Feche esta janela ou aperte Ctrl+C para parar.
uvicorn app.main:app --reload
pause
