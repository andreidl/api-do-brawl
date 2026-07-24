# DEPLOY — Fase 3 (VM Oracle Always Free, público 24/7, HTTPS grátis)

Runbook do deploy. O objetivo: `https://SEU.duckdns.org` abrindo qualquer tag ao
vivo, sempre no ar, custo zero. Segredos **nunca** entram no repo (público).

Arquitetura na VM:
```
Internet ──443──▶ Caddy (HTTPS automático) ──▶ 127.0.0.1:8000 uvicorn (systemd)
                                                     │
                                                     ├─▶ API oficial Brawl Stars
                                                     └─▶ Postgres (Supabase)
   systemd timer ──a cada 2h──▶ python -m app.rastrear
```

---

## Parte A — SÓ VOCÊ faz (console/contas)

> **Host: Google Cloud Always Free** (e2-micro). Grátis-para-sempre, 24/7, IP
> fixo, SSH pelo navegador. (Para a variante Oracle, veja o apêndice no fim.)

### A1. Criar a VM (Google Cloud, Always Free)
1. https://console.cloud.google.com → crie um projeto (ex.: `apidobrawl`).
2. **Compute Engine → VM instances → Create instance** (habilite a API se pedir).
3. **Region**: OBRIGATÓRIO uma das do Always Free — `us-west1` (Oregon),
   `us-central1` (Iowa) ou `us-east1` (Carolina do Sul). Fora delas, é cobrado.
4. **Machine type**: série **E2** → **`e2-micro`** (o tier gratuito).
5. **Boot disk**: troque para **Ubuntu 22.04 LTS**, disco **Standard** ≤ 30 GB.
6. **Firewall**: marque **Allow HTTP traffic** e **Allow HTTPS traffic**
   (isto cria as regras de firewall 80/443 — não precisa mexer em VPC à mão).
7. Create. Anote o **External IP**.

### A2. Fixar o IP (pra não mudar) — grátis enquanto anexado
1. **VPC network → IP addresses** (ou "IP externos").
2. Na linha do IP externo da VM, **Reserve / Promote to static**. Dê um nome.
> IP estático é grátis enquanto estiver **anexado a uma VM ligada** (a nossa fica
> 24/7). Isso garante que o IP registrado no token (A4) não mude.

### A3. DuckDNS (subdomínio grátis + HTTPS bonito)
1. https://www.duckdns.org → login → crie um subdomínio (ex.: `apidobrawl`).
2. Aponte o campo **IP** para o **IP público da VM** (A1). Salve.
3. Guarde o **token** do DuckDNS (só precisa se for usar o auto-update — Parte C).
- Domínio final: `apidobrawl.duckdns.org`.

### A4. Registrar o IP da VM no token da Supercell
1. https://developer.brawlstars.com → sua **API Key** (ou crie uma nova).
2. Em **Allowed IP Addresses**, adicione o **IP público da VM**.
3. Copie o token — vai em `BRAWL_API_TOKEN` no `/etc/apidobrawl.env` (Parte B).
> Sem o IP certo na key, a API oficial responde 403.

---

## Parte B — Provisionamento (roda na VM)

Conecte via **SSH do navegador**: no console, VM instances → botão **SSH** na
linha da VM (abre um terminal, sem configurar chave). No GCP o usuário é o seu
login Google, com `sudo`.

```bash
# 1) pega o script (repo é público)
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/andreidl/api-do-brawl.git /tmp/apidobrawl-src
cd /tmp/apidobrawl-src

# 2) rode o provisionador — no GCP pule o iptables local (AJUSTAR_IPTABLES=0)
DOMINIO=apidobrawl.duckdns.org AJUSTAR_IPTABLES=0 bash deploy/setup.sh
```

O `setup.sh` instala tudo, clona o repo em `/opt/apidobrawl`, cria o venv,
gera os serviços systemd + Caddyfile, abre 80/443 no iptables e sobe os serviços.
Na primeira vez ele cria `/etc/apidobrawl.env` **vazio**.

```bash
# 3) preencha os segredos (token com o IP da VM + a MESMA DATABASE_URL da Fase 2)
sudo nano /etc/apidobrawl.env
#   BRAWL_API_TOKEN=...   DATABASE_URL=postgres://...   BRAWL_RASTREIO=0

# 4) reinicie o app pra carregar os segredos
sudo systemctl restart apidobrawl
```

### Verificação
```bash
sudo systemctl status apidobrawl --no-pager
curl -sS http://127.0.0.1:8000/ | head -c 200      # HTML da home = app no ar
sudo journalctl -u apidobrawl -n 50 --no-pager     # logs do web
sudo systemctl list-timers apidobrawl-rastreio*    # próximo disparo do rastreio
```
Depois, do seu PC: abra **https://apidobrawl.duckdns.org** (o cadeado é o Caddy
emitindo o certificado Let's Encrypt automaticamente).

---

## Parte C — DuckDNS auto-update (opcional, recomendado)

Mantém o subdomínio apontando pro IP certo mesmo se ele mudar. Na VM:

```bash
sudo tee /etc/duckdns.env >/dev/null <<'EOF'
DUCKDNS_DOMINIO=apidobrawl
DUCKDNS_TOKEN=SEU_TOKEN_DUCKDNS
EOF
sudo chmod 600 /etc/duckdns.env

sudo tee /usr/local/bin/duckdns-update.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -a; source /etc/duckdns.env; set +a
curl -sS "https://www.duckdns.org/update?domains=${DUCKDNS_DOMINIO}&token=${DUCKDNS_TOKEN}&ip="
EOF
sudo chmod +x /usr/local/bin/duckdns-update.sh

sudo tee /etc/systemd/system/duckdns.service >/dev/null <<'EOF'
[Unit]
Description=Atualiza o IP no DuckDNS
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/duckdns-update.sh
EOF

sudo tee /etc/systemd/system/duckdns.timer >/dev/null <<'EOF'
[Unit]
Description=DuckDNS a cada 30min
[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload && sudo systemctl enable --now duckdns.timer
```

---

## Atualizar o app depois (nova versão)
```bash
cd /opt/apidobrawl && DOMINIO=apidobrawl.duckdns.org bash deploy/setup.sh
# (faz git reset --hard origin/main, reinstala deps e reinicia os serviços)
```

## Rastreador manual (rodar uma volta na hora)
```bash
sudo systemctl start apidobrawl-rastreio.service
sudo journalctl -u apidobrawl-rastreio -n 50 --no-pager
```

## Troubleshooting rápido
| Sintoma | Causa provável |
|---|---|
| `https://` não abre, mas `curl 127.0.0.1:8000` funciona | Firewall 80/443 fechado: no **GCP** marque Allow HTTP/HTTPS (A1.6); no **Oracle** libere na Security List |
| Caddy não emite certificado | DNS do DuckDNS não aponta pro IP, ou porta 80 bloqueada |
| App sobe mas API oficial dá 403 | IP da VM não está na **key** da Supercell (A4) |
| `psycopg`/conexão falha | `DATABASE_URL` errada no `/etc/apidobrawl.env` |
| Rastreio não grava meta | Scraping (brawlace) bloqueado no IP de datacenter → **Fase 4** |

> **Nota Fase 4:** o *core* (perfil/batalhas) usa a **API oficial** e funciona da
> VM. O **meta/picks** ainda vem de scraping (brawlace/brawltime), que pode ser
> bloqueado no IP da VM. Se bloquear, o PC do usuário alimenta o meta no mesmo
> Postgres (ver `plano_online.md` §Fase 4).

---

## Apêndice — variante Oracle Cloud (alternativa ao GCP)

Se um dia usar a Oracle no lugar do GCP, mudam só as etapas de infra:
- **A1 (VM):** OCI → Compute → Create instance → Ubuntu 22.04 →
  shape **`VM.Standard.E2.1.Micro`** (AMD) → suba sua chave SSH pública.
- **A2 (portas):** libere **80/443** na **Security List** da VCN (Ingress,
  `0.0.0.0/0`, TCP). As imagens Oracle **também** bloqueiam no iptables local →
  rode o `setup.sh` **sem** `AJUSTAR_IPTABLES=0` (deixe o default `=1`).
- **SSH:** `ssh ubuntu@IP` com a sua chave (não tem SSH de navegador).
- A3 (DuckDNS) e A4 (IP no token) são iguais.
