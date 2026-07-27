#!/usr/bin/env bash
# =============================================================================
# API do Brawl — provisionamento da VM Oracle (Ubuntu) — Fase 3.
#
# Idempotente: pode rodar de novo pra atualizar o código/serviços.
# Sobe: FastAPI (uvicorn) sob systemd, sempre no ar + HTTPS grátis (Caddy) +
# timer do rastreador. Segredos ficam em /etc/apidobrawl.env (FORA do git).
#
# USO (na VM, como usuário com sudo — ex.: ubuntu):
#   1) edite as variáveis abaixo (DOMINIO obrigatório p/ HTTPS)
#   2) bash deploy/setup.sh
#
# Pré-requisitos que SÓ VOCÊ faz (ver deploy/DEPLOY.md):
#   - abrir portas 80 e 443 na Security List/NSG do OCI (console Oracle)
#   - apontar o subdomínio DuckDNS pro IP público da VM
#   - registrar o IP público da VM no token da Supercell (developer.brawlstars.com)
# =============================================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # evita prompts (ex.: iptables-persistent)

# ----------------------------- CONFIGURAÇÃO ----------------------------------
DOMINIO="${DOMINIO:-SEU_SUBDOMINIO.duckdns.org}"   # ex.: apidobrawl.duckdns.org
APP_USER="${APP_USER:-$(whoami)}"                  # dono do app (ex.: ubuntu)
APP_DIR="${APP_DIR:-/opt/apidobrawl}"              # onde o repo vai ficar
REPO_URL="${REPO_URL:-https://github.com/andreidl/api-do-brawl.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
ENV_FILE="/etc/apidobrawl.env"                     # segredos (600, root)
PORTA_APP="${PORTA_APP:-8000}"                     # uvicorn local (atrás do Caddy)
# Oracle bloqueia 80/443 no iptables local; GCP/AWS não. 1=ajusta (Oracle), 0=pula.
AJUSTAR_IPTABLES="${AJUSTAR_IPTABLES:-1}"
# -----------------------------------------------------------------------------

echo ">>> [1/8] Pacotes base (python, git, caddy)…"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git curl \
     debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
  echo ">>> instalando Caddy (repo oficial)…"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

echo ">>> [2/8] Código em ${APP_DIR}…"
if [ ! -d "${APP_DIR}/.git" ]; then
  sudo mkdir -p "${APP_DIR}"
  sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
  git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch --all --quiet
  git -C "${APP_DIR}" reset --hard "origin/${REPO_BRANCH}"
fi

echo ">>> [2.5/8] Swap (evita OOM em VM de 1 GB, ex.: e2-micro)…"
if [ ! -f /swapfile ] && ! swapon --show | grep -q .; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo "    swap de 2G criado."
else
  echo "    swap já existe — ok."
fi

echo ">>> [3/8] Virtualenv + dependências…"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip --quiet
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" --quiet

echo ">>> [4/8] Arquivo de segredos ${ENV_FILE}…"
if [ ! -f "${ENV_FILE}" ]; then
  sudo tee "${ENV_FILE}" >/dev/null <<'EOF'
# Segredos da API do Brawl — NÃO versionar. Preencha e rode: sudo systemctl restart apidobrawl
BRAWL_API_TOKEN=
DATABASE_URL=
# Rastreador roda por systemd timer, não pela thread embutida do app:
BRAWL_RASTREIO=0
EOF
  sudo chmod 600 "${ENV_FILE}"
  echo "    !! ${ENV_FILE} criado VAZIO — preencha BRAWL_API_TOKEN e DATABASE_URL e rode este script de novo (ou reinicie os serviços)."
fi

echo ">>> [5/8] Units do systemd (web + rastreador)…"
sudo tee /etc/systemd/system/apidobrawl.service >/dev/null <<EOF
[Unit]
Description=API do Brawl (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${PORTA_APP}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/apidobrawl-rastreio.service >/dev/null <<EOF
[Unit]
Description=API do Brawl — rodada de rastreamento
After=network-online.target apidobrawl.service
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -m app.rastrear
EOF

sudo tee /etc/systemd/system/apidobrawl-rastreio.timer >/dev/null <<EOF
[Unit]
Description=API do Brawl — dispara o rastreamento a cada 2h

[Timer]
OnBootSec=3min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo ">>> [6/8] Caddyfile (HTTPS automático p/ ${DOMINIO})…"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMINIO} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:${PORTA_APP}
}
EOF

if [ "${AJUSTAR_IPTABLES}" = "1" ]; then
  echo ">>> [7/8] Firewall local (iptables) p/ 80/443 — gotcha das imagens Oracle…"
  # As imagens Ubuntu do OCI vêm com iptables bloqueando tudo menos SSH.
  # (Isto NÃO substitui liberar 80/443 na Security List do OCI — ver DEPLOY.md.)
  # Insere no TOPO (posição 1) — honra o ACCEPT antes de qualquer REJECT da imagem,
  # e funciona independente de quantas regras existirem. Idempotente pelo -C.
  sudo iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || \
    sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
  sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
    sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save 2>/dev/null || \
    (sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save)
else
  echo ">>> [7/8] iptables local: PULADO (AJUSTAR_IPTABLES=0 — ex.: GCP/AWS)."
fi

echo ">>> [8/8] Habilitando e subindo os serviços…"
sudo systemctl daemon-reload
sudo systemctl enable --now apidobrawl.service
sudo systemctl enable --now apidobrawl-rastreio.timer
sudo systemctl reload caddy || sudo systemctl restart caddy

echo ""
echo "=============================================================="
echo " Pronto. Verifique:"
echo "   sudo systemctl status apidobrawl --no-pager"
echo "   curl -sS http://127.0.0.1:${PORTA_APP}/ | head -c 200"
echo "   https://${DOMINIO}   (após DNS + portas OCI + IP no token)"
echo ""
echo " Se ${ENV_FILE} estava vazio, preencha os segredos e rode:"
echo "   sudo systemctl restart apidobrawl"
echo "=============================================================="
