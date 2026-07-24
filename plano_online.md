# PLANO — API do Brawl PÚBLICA, ONLINE e GRÁTIS

> Documento de arquitetura e migração. Escrito em 24/07/2026 para aprovação
> ANTES de codar. Não substitui o `plano.md` (fila do dia a dia); complementa.

## 0. OBJETIVO E REQUISITOS (fechados com o usuário)

Transformar o app (hoje local, SQLite, rastreio quando o PC está ligado) em:

- **Público**: qualquer visitante consulta **qualquer tag** ao vivo.
- **Online 24/7**: sem hibernar.
- **Grátis**: custo zero, sempre.

Decisões tomadas (24/07/2026) — TODAS fechadas:

| Tema | Escolha |
|---|---|
| Fonte de dados principal | **API oficial** do Brawl Stars (JSON), via IP fixo da VM (sem proxy) |
| Meta / picks / conta | **Manter scraping à parte**; se o IP da VM for bloqueado, **o PC do usuário alimenta o meta** no Postgres |
| Histórico | **Só o clã acumula**; visitantes aleatórios veem ao vivo (25 batalhas) sem gravar |
| Banco | **Postgres grátis (Supabase)** externo |
| Dev local | **SQLite mantido** (`DATABASE_URL` ausente = SQLite; presente = Postgres) |
| Backup do banco | **`pg_dump` periódico versionado** no repo |
| Hospedagem | **Google Cloud Always Free** (`e2-micro`, us-west1/central1/east1) — trocado da Oracle em 24/07 (cadastro rejeitou). Oracle vira alternativa. |
| Deploy | usuário **dá acesso SSH**; eu configuro |
| HTTPS/URL | **DuckDNS + Caddy** (subdomínio grátis + HTTPS automático) |
| Proteção do endpoint público | **cache curto por tag + limite por IP** |
| Repositório | **público** (segredos nunca no repo) |
| Publicação estática atual | **aposentar** `exportar.py`/`publicar.bat` |
| Prioridade em conflito | **Custo zero acima de tudo** |

## 1. ARQUITETURA-ALVO

```
Visitante ──HTTPS──▶ VM Oracle Always Free (IP FIXO)
                        │  FastAPI (uvicorn + Caddy p/ HTTPS grátis)
                        │  systemd: app sempre no ar + timer do rastreador
                        ├──▶ API oficial brawlstats  (IP da VM registrado no token)
                        │       perfil · battlelog(25) · clube · rankings · eventos
                        └──▶ Postgres grátis (Supabase ou Neon)
                                acumula batalhas/snapshots/meta além das 25

Meta/picks (brawlace, brawltime):
   raspado da VM SE o IP passar; se bloquear → raspado do PC do usuário
   e gravado no MESMO Postgres (o app público só LÊ o meta de lá).
```

Por que Oracle: única opção **grátis-para-sempre + sempre-ligada + IP fixo**.
O IP fixo é registrado direto no token da Supercell → **dispensa o proxy
RoyaleAPI** (o proxy fica como plano B se o IP da VM der problema).

## 2. O QUE A API OFICIAL COBRE (e o que não cobre)

Base: `https://api.brawlstars.com/v1` (tag com `#` → `%23`, UPPERCASE).

| Endpoint | Alimenta |
|---|---|
| `/players/{tag}` | nick, troféus, level, vitórias 3v3/solo/duo, clube, **brawlers** (power, rank, star powers/gadgets/gears que POSSUI) |
| `/players/{tag}/battlelog` | **últimas 25 batalhas**: `battleTime`, `event{mode,map}`, `battle{type, result, duration, trophyChange, starPlayer, teams[]}` |
| `/clubs/{tag}` | roster do clube |
| `/rankings/{pais}/players\|brawlers` | rankings |
| `/events/rotation` | **eventos ativos** (modo+mapa+horários) — substitui o scraping de `/events` |
| `/brawlers` | referência de brawlers |

**NÃO existe na API** (por isso o scraping à parte continua): **meta** (% star
player por modo — brawlace `/meta`), **brawltime** (winrate por mapa, best teams),
**brawlytix** (valor da conta, skill), **Brawlify** (histórico antigo — já é manual).

Ganho de qualidade: o battlelog vem estruturado. O campo `battle.type` +
`trophyChange` resolvem a classificação RANKED/TROFÉU **de forma nativa** (o bug
que consertamos hoje some — a regra vira direta pela API).

## 3. FASES (cada uma testável e reversível)

### Fase 1 — Coleta via API oficial
- **Eu faço:** `app/coleta/oficial.py` com `coletar_perfil`, `coletar_battlelog`,
  `coletar_clube`, `coletar_eventos`, `coletar_rankings`. Mapear o JSON pro mesmo
  formato de dicts que o resto do app já consome (perfil/batalhas/brawlers), pra
  reaproveitar `indicadores/*` e templates. Fixtures de JSON real + testes pytest.
- **Você faz:** criar conta em **developer.brawlstars.com**, gerar um **token**.
  (No começo dá pra registrar seu IP residencial pra testar local; na Fase 3
  troca pelo IP fixo da VM.) Me passa o token via variável de ambiente
  `BRAWL_API_TOKEN` — **nunca** no repo.
- **Valida:** rodar local, comparar dados da API com o que o brawlace dava.
- **Reversível:** brawlace continua no código; só adicionamos a fonte oficial.

### Fase 2 — Persistência em Postgres ✅ FEITA (24/07/2026)
- **Feito:** `app/db.py` agora é **dual-backend**. `conectar()` abre Postgres
  quando `DATABASE_URL` está setada e nenhum caminho é passado; senão SQLite
  (passar caminho força SQLite → testes intactos). Wrapper `_ConexaoPG` imita a
  fatia usada da API do sqlite3 e traduz `?`→`%s`. SQL das funções ficou portável
  (`ON CONFLICT`, `CASE` no lugar de `MAX(a,b)`, sem alias em `HAVING`, colunas do
  `DO UPDATE` qualificadas). `main.py`/`meta.py` ajustados (except `db.ErrosBanco`,
  acesso a coluna nomeado). Schema PG com `GENERATED IDENTITY`, sem FKs reforçadas.
- **Import:** `python -m app.importar_para_postgres [--forcar]` espelha o
  `brawl.db` no Postgres (truncate-then-load idempotente; ids seriais regerados).
  Import inicial: **8.606 linhas** (jogadores, snapshots, batalhas globais, meta,
  histórico Brawlify, clube) preservadas.
- **Decisão tomada:** dev local mantém **SQLite** (`DATABASE_URL` ausente) — não
  depende de rede no dev; produção usa Postgres.
- **Validado:** 101 testes SQLite verdes; leituras + escritas (`salvar_consulta`
  idempotente, `salvar_score_meta` DO UPDATE) OK no Supabase; home FastAPI (`/`)
  renderiza contra o Postgres.
- **Limitação conhecida:** `app/importar_brawlify.py` (import manual do histórico
  Brawlify) ainda é SQLite-only — roda no PC local; portar pra PG fica p/ depois.

### Fase 3 — Deploy público 24/7 ✅ FEITA (24/07/2026) — https://clasnake.duckdns.org
- **No ar:** VM **Google Cloud e2-micro** (`us-central1`, IP `34.56.27.80`),
  Ubuntu, FastAPI/uvicorn sob systemd (`Restart=always`, boot automático), HTTPS
  automático via Caddy, domínio **`clasnake.duckdns.org`** (DuckDNS). Rastreador
  por systemd timer 2h. `setup.sh` rodou com `AJUSTAR_IPTABLES=0`.
- **Gotcha resolvido (importante):** o host **direto** do Supabase
  (`db.<ref>.supabase.co`) só responde por **IPv6** no free; a VM GCP é só IPv4
  → "Network is unreachable". Solução: `DATABASE_URL` usa o **Session pooler**
  (`postgres.<ref>@aws-0-<região>.pooler.supabase.com:5432`), que é IPv4.
- **Firewall:** GCP 80/443 abertos pelos checkboxes Allow HTTP/HTTPS na VM.
- **Token:** key nova com IP `34.56.27.80` na allowlist (a antiga não deixava
  editar IP). Segredos só em `/etc/apidobrawl.env` (600, fora do git).
- **Pendências pós-deploy:** (1) trocar a senha do Postgres (foi exposta no chat);
  (2) opcional: reservar o IP como estático + DuckDNS auto-update (Parte C do
  `DEPLOY.md`). (3) rastreador ainda usa scraping brawlace — ver Fase 4.

### Fase 3 (histórico) — artefatos de deploy
- **Feito (código):** pacote de deploy em `deploy/` — `setup.sh` (provisiona
  Ubuntu: Python+venv, Caddy, clone do repo, units systemd, Caddyfile, iptables
  80/443, sobe tudo — idempotente), units web + rastreador (systemd timer 2h),
  `env.example` (`/etc/apidobrawl.env`), `DEPLOY.md` (runbook completo).
  `.gitattributes` força LF nos scripts. Na VM o rastreador usa o **timer**
  (`BRAWL_RASTREIO=0` desliga a thread embutida).
- **Host trocado (24/07):** cadastro da Oracle rejeitou → **Google Cloud Always
  Free** (`e2-micro`, us-west1/central1/east1). Grátis-para-sempre, 24/7, IP fixo,
  SSH pelo navegador. Deploy reaproveitado 100% (`setup.sh` ganhou flag
  `AJUSTAR_IPTABLES=0` p/ GCP; firewall 80/443 vai nos checkboxes da VM). Oracle
  vira apêndice no `DEPLOY.md`.
- **Falta (só você):** criar a VM `e2-micro` (Ubuntu, região do free tier),
  marcar Allow HTTP/HTTPS, reservar IP estático, apontar o **DuckDNS** pro IP,
  registrar o **IP da VM no token** da Supercell. Depois:
  `DOMINIO=... AJUSTAR_IPTABLES=0 bash deploy/setup.sh` + preencher
  `/etc/apidobrawl.env`. Passo-a-passo em `deploy/DEPLOY.md`.
- **Valida:** `https://SEU.duckdns.org` abre qualquer tag, 24/7, sem hibernar.

### Fase 4 — Meta / picks (scraping à parte)
- **Eu faço:** primeiro **testar** se brawlace/brawltime respondem do IP da VM.
  - Se **sim**: rastreador da VM raspa o meta e grava no Postgres.
  - Se **não** (provável p/ brawltime): o **PC do usuário** raspa o meta quando
    ligado e grava no MESMO Postgres; o app público só **lê**. O core (API) fica
    sempre fresco; o meta fica "foto" na cadência do PC.
- **Valida:** seções de meta/picks aparecem no site público.

## 4. CONTAS E SEGREDOS (só você cria; eu ligo via env)

| Serviço | Para quê | Segredo |
|---|---|---|
| developer.brawlstars.com | token da API oficial | `BRAWL_API_TOKEN` |
| Supabase **ou** Neon | Postgres grátis | `DATABASE_URL` |
| Oracle Cloud | VM Always Free 24/7 | acesso SSH (seu) |
| DuckDNS (opcional) | subdomínio grátis p/ HTTPS | — |

**Regra de ouro:** nenhum segredo entra no repositório público. Tudo em variável
de ambiente na VM (arquivo de env fora do git). Eu **não** crio contas nem digito
credenciais suas.

## 5. RISCOS E MITIGAÇÕES

| Risco | Mitigação |
|---|---|
| Scraping de meta bloqueado no IP da VM (datacenter) | Fase 4: PC raspa o meta → grava no Postgres compartilhado |
| Postgres grátis com limite (Supabase 500MB / pausa por inatividade; Neon auto-suspende) | App público tem tráfego → não pausa; limpar tags aleatórias antigas se encher |
| Oracle recuperar instância ARM ociosa | usar VM **AMD micro** (mais estável) ou manter ativa |
| API oficial: campos diferentes do brawlace | Fase 1 valida com fixtures antes de trocar |
| Banco cresce sem limite (qualquer tag pública) | política de retenção (ex.: manter só clã + consultados recentes) |
| Perder o histórico já acumulado | import único do `brawl.db` → Postgres na Fase 2 |
| Token exposto | só em env na VM; se vazar, regenerar na Supercell |

## 6. O QUE MUDA / SE MANTÉM / SE PERDE

- **Mantém:** todos os indicadores (winrate por modo/mapa/brawler, forma, cards,
  troféus por brawler, etc.), o design de batalhas globais, o acúmulo de histórico.
- **Melhora:** classificação RANKED/TROFÉU (nativa pela API), estabilidade (sem
  anti-bot no core), sempre online.
- **Muda:** fonte do core (brawlace→API oficial), banco (SQLite→Postgres), host.
- **Fica dependente de scraping (risco):** meta, picks por meta, conta Brawlytix.
- **Segue manual:** histórico Brawlify de tags novas.

## 7. DECISÕES — TODAS RESOLVIDAS (24/07/2026)

Ver a tabela do §0. Nada em aberto. Consequências de design das escolhas:

- **"Só o clã acumula"**: membros do clã têm batalhas/snapshots gravados e
  histórico acumulado (matchups/parceiros via hash global entre eles). Tag de
  visitante aleatório → chamada à API ao vivo, mostra 25 batalhas + stats atuais,
  **não grava** (aviso de amostra pequena). Banco pequeno e previsível.
- **Cache curto + limite por IP**: cada tag consultada fica em cache alguns
  minutos (não repete chamada à API); rate-limit por IP evita abuso. Protege o
  limite da API oficial.
- **Meta**: gravado no Postgres. Preenchido pela VM se o IP passar, senão pelo PC
  do usuário. O app público só LÊ o meta de lá (vale pra qualquer tag).

## 8. ORDEM SUGERIDA E "DEFINIÇÃO DE PRONTO"

1. Aprovar este plano.
2. Você cria o token (developer.brawlstars.com) → **Fase 1** (coleta oficial, validada local).
3. Você cria o Postgres → **Fase 2** (migração + import, validada local).
4. Você cria a VM Oracle → **Fase 3** (deploy público 24/7).
5. **Fase 4** (meta/picks) conforme o teste de IP.

Pronto = URL pública abrindo qualquer tag ao vivo, 24/7, custo zero, com o
histórico preservado.
